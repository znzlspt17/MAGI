# 테스트 안내

제품 테스트와 테스트 전용 fixture·mock·QA 화면은 이 디렉터리에 모읍니다. 패키지별 테스트 경로는 제품 소스 구조를 따릅니다. 여러 패키지 사이의 계약을 검증하는 테스트는 `integration/`, 저장소 전체 구조를 검증하는 테스트는 `architecture/`에 둡니다.

| 경로 | 검증 목적 |
| --- | --- |
| `backend/<패키지>/` | 해당 백엔드 패키지의 모델, 처리 흐름, 저장·접근 경계 |
| `gateway/` | HTTP·WebSocket·MCP 게이트웨이 동작 |
| `protocol/` | 메시지·명령 계약과 로깅 벤치마크 |
| `deploy/` | 배포 구성, 산출물, 로그 수집 구성과 Vector 테스트 정의 |
| `frontend/src/features/<기능>/` | 기능별 컴포넌트·상태·응답 계약 |
| `frontend/src/shared/<패키지>/` | 공통 API와 UI |
| `frontend/scripts/` | 라이선스 고지 생성 도구 |
| `frontend/qa/` | 실제 앱 컴포넌트와 가짜 API를 사용하는 수동 UI 검증 환경 |
| `integration/` | 패키지 간 실행·통신·계약 통합 |
| `architecture/` | 의존 방향과 실행 진입점 등 저장소 전체 규칙 |
| `e2e/` | 빌드한 화면과 가짜 모델 응답을 사용하는 실제 브라우저 시나리오 |
| `support/` | 여러 Python 테스트가 공유하는 fixture·fake와 SQL 검증 브리지 |
| `conftest.py` | 공통 pytest DB fixture |

## 실행 방법

저장소 루트에서 실행합니다.

```sh
uv sync --locked --extra test --group gateway
pnpm --dir frontend install --frozen-lockfile
uv run python -m pytest -q
pnpm --dir frontend test
pnpm --dir frontend typecheck
pnpm --dir frontend build
```

Python 테스트는 경로로 선택할 수 있습니다.

```sh
uv run python -m pytest -q tests/backend/pipeline
uv run python -m pytest -q tests/architecture tests/protocol
uv run python -m pytest -q tests/e2e
```

프런트엔드 의존성은 기존 `frontend/node_modules`를 사용합니다. 테스트 이동을 위해 별도 설치 위치나 패키지를 추가하지 않습니다. 수동 QA 실행 명령과 재현 가능한 화면 상태는 [QA 안내](frontend/qa/README.md)를 참고하세요.

## 실행 조건과 검증 범위

- DB 테스트는 CI의 전용 PostgreSQL·pgvector와 공식 PostgreSQL checkpointer를 사용합니다. 로컬 대체 검사는 별도 PGlite+pgvector 런타임을 사용하며, 미설치 시 해당 검사를 건너뜁니다. 로컬 대체 검사는 PostgreSQL 운영 복구 검증을 대신하지 않습니다.
- 실제 RabbitMQ 검사는 전용 CI 브로커와 `CI_RABBITMQ=1` 설정이 필요합니다. 운영 브로커를 연결하지 않습니다.
- Docker 로그 수집·복구 검사는 Docker와 명시적인 `MAGI_RUN_LOG_STACK_TESTS=1` 설정이 필요합니다.
- 브라우저 E2E는 프런트엔드 빌드와 Playwright Chromium이 필요합니다. `pnpm --dir frontend exec playwright install chromium`으로 브라우저를 준비합니다.
- E2E와 수동 QA는 실제 모델 품질이나 운영 계정·서비스를 검증하지 않습니다. 보호된 환경 파일과 인증정보는 읽지 않습니다.

새 테스트는 검증 대상 패키지 아래에 추가하고, 파일명과 테스트 설명으로 확인하려는 동작을 명시합니다. 공유 지원 코드는 `tests.support` 패키지에서 명시적으로 import하며, 테스트 실행 경로에 의존하는 짧은 모듈 import는 피합니다.
