"""접속값을 표현하거나 로그에 남기지 않는 실행 설정."""

from dataclasses import dataclass, field
import os
from pathlib import Path


class KnowledgeError(RuntimeError):
    """외부로 전달해도 접속 정보가 노출되지 않는 오류."""


@dataclass(repr=False)
class KnowledgeConfig:
    connection: dict = field(repr=False)
    model_path: Path | None = None
    device: str = "cpu"

    @classmethod
    def from_env(cls, *, allow_legacy_model=False):
        from protocol.environment import require_current_environment
        require_current_environment()
        names = {"host": "HOST", "dbname": "NAME", "user": "USER", "password": "PASSWORD"}
        values = {key: os.environ.get("DB_" + suffix, "") for key, suffix in names.items()}
        configured = any("DB_" + suffix in os.environ for suffix in (*names.values(), "PORT", "SSLMODE"))
        if not configured:
            return None  # 기존 파일 전용 설치와 Python API의 호환 경로
        if not all(values.values()):
            raise KnowledgeError("DB 필수 설정이 누락되었습니다.")
        try:
            port = int(os.environ.get("DB_PORT", "5432"))
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            raise KnowledgeError("DB 포트 설정이 올바르지 않습니다.") from None
        sslmode = os.environ.get("DB_SSLMODE", "prefer")
        if sslmode not in {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}:
            raise KnowledgeError("DB TLS 설정이 올바르지 않습니다.")
        device = os.environ.get("EMBEDDING_DEVICE", "cpu")
        if device != "cpu":
            raise KnowledgeError("BGE-M3 임베딩 장치는 cpu여야 합니다.")
        model = os.environ.get("EMBEDDING_MODEL_PATH")
        from backend.knowledge.format_guard import require_current_model
        if not allow_legacy_model:
            require_current_model(model)
        return cls({**values, "port": port, "sslmode": sslmode, "connect_timeout": 5},
                   Path(model) if model else None, device)


def load_environment():
    from protocol.environment import require_current_environment
    require_current_environment()
    # 실행 프로그램만 호출한다. 테스트와 모듈 import는 보호 파일을 읽지 않는다.
    if os.environ.get("CONTAINER") == "1":
        return  # 컨테이너는 운영자가 주입한 환경만 사용한다.
    from dotenv import load_dotenv
    load_dotenv(Path.cwd() / ".env", override=False)
    require_current_environment()
