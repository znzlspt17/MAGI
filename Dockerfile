# syntax=docker/dockerfile:1.7.0
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
ARG NODE_IMAGE=node:24-bookworm-slim@sha256:a5f4366e834695d5f363b920c104953a535d3a9864d1bdf74566a0ebe01daee5

FROM --platform=$BUILDPLATFORM ${NODE_IMAGE} AS frontend-build
WORKDIR /frontend
RUN npm install --global pnpm@11.25.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/src ./src
COPY frontend/scripts ./scripts
COPY frontend/static/vendor ./static/vendor
COPY resources /resources
COPY frontend/tsconfig.json frontend/vite.config.ts ./
RUN pnpm build

FROM ${PYTHON_IMAGE} AS python-build
WORKDIR /app
RUN pip install --no-cache-dir uv==0.10.0
COPY pyproject.toml uv.lock ./
COPY resources/licenses/python_notices.py /app/python_notices.py

FROM python-build AS gateway-deps
RUN uv sync --frozen --no-dev --only-group gateway --no-install-project --no-build
RUN .venv/bin/python python_notices.py --output /notices

FROM python-build AS backend-deps
RUN uv sync --frozen --no-dev --extra embedding --no-install-project --no-build
RUN .venv/bin/python -c "from importlib.metadata import distributions; assert not any(d.metadata['Name'].lower().startswith(('nvidia-', 'cuda-', 'triton')) for d in distributions())"
RUN .venv/bin/python python_notices.py --output /notices

# 공개 고지는 backend(embedding 포함)와 gateway의 실제 설치 결과를 합친다.
FROM gateway-deps AS combined-notices
COPY --from=backend-deps /notices /backend-notices
COPY --from=frontend-build /frontend/static/vendor /frontend-notices
# 저장소의 로컬 Python 목록 대신 각 Linux 이미지의 목록을 사용한다.
RUN .venv/bin/python -c "import json; from pathlib import Path; p=Path('/frontend-notices/third-party-licenses.json'); p.write_text(json.dumps([e for e in json.loads(p.read_text()) if not e['name'].endswith(' (Python)')]))"
RUN .venv/bin/python python_notices.py --output /notices --merge /backend-notices/third-party-licenses.json --merge /frontend-notices/third-party-licenses.json

FROM ${PYTHON_IMAGE} AS runtime
RUN apt-get update && apt-get install --yes --no-install-recommends ca-certificates libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    CONTAINER=1 FLASK_SKIP_DOTENV=1 HOME=/tmp \
    HF_HOME=/tmp/huggingface HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
    TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
USER 10001:10001

FROM runtime AS gateway
COPY --from=gateway-deps /app/.venv /app/.venv
COPY gateway ./gateway
COPY protocol ./protocol
COPY frontend/__init__.py ./frontend/__init__.py
COPY frontend/templates ./frontend/templates
COPY --from=frontend-build /frontend/static/dist ./frontend/static/dist
COPY --from=frontend-build /frontend/static/vendor ./frontend/static/vendor
COPY --from=combined-notices /notices/third-party-licenses.json ./frontend/static/vendor/third-party-licenses.json
COPY --from=combined-notices /notices/THIRD_PARTY_NOTICES.txt ./frontend/static/vendor/THIRD_PARTY_NOTICES.txt
CMD ["gunicorn", "--workers", "1", "--threads", "16", "--bind", "127.0.0.1:5000", "--timeout", "600", "--graceful-timeout", "590", "gateway.app:create_app()"]

FROM runtime AS backend
COPY --from=backend-deps /app/.venv /app/.venv
COPY --from=backend-deps /notices /app/notices
COPY backend ./backend
COPY protocol ./protocol
CMD ["python", "-m", "protocol.container", "python", "-m", "backend.server"]
