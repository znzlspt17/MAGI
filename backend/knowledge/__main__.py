"""DB 설치·전환·검증과 검색 색인 관리. 서버 시작은 스키마를 변경하지 않는다."""

import argparse
import json
from backend.knowledge.config import KnowledgeConfig, KnowledgeError
from backend.knowledge.store import KnowledgeStore


def main():
    parser = argparse.ArgumentParser(
        description="접속 정보는 운영자가 환경으로 주입합니다."
    )
    parser.add_argument("command", choices=["install", "migrate", "verify", "reindex"])
    parser.add_argument("--application-role", default="app_user")
    args = parser.parse_args()
    config = KnowledgeConfig.from_env()
    if config is None:
        parser.error("PostgreSQL 설정이 필요합니다.")
    store = KnowledgeStore(config)
    phase = args.command
    try:
        if args.command == "install":
            from backend.knowledge.upgrade import install

            install(store)
            result = {"phase": "installed"}
        elif args.command == "migrate":
            from backend.knowledge.upgrade import (
                migrate_business,
                initialize_checkpoints,
                convert_checkpoints,
            )

            phase = "migrate_business"
            counts = migrate_business(store)
            phase = "initialize_checkpoints"
            initialize_checkpoints(store)
            phase = "convert_checkpoints"
            converted = convert_checkpoints(store)
            result = {
                "phase": "converted",
                "jobs": converted,
                "source_counts": {k: v["count"] for k, v in counts.items()},
            }
        elif args.command == "verify":
            from backend.knowledge.upgrade import verify_and_enable

            result = verify_and_enable(store, application_role=args.application_role)
        else:
            store.require_ready()
            from backend.knowledge.runtime import KnowledgeService

            service = KnowledgeService(store)
            try:
                if not service.reindex():
                    raise KnowledgeError(service.last_error)
                result = {"status": "completed"}
            finally:
                service.close()
        print(json.dumps(result, ensure_ascii=False))
    except KnowledgeError as exc:
        parser.exit(1, "단계: " + phase + " — " + str(exc) + "\n")
    except Exception as exc:
        parser.exit(
            1,
            "설치·전환을 완료하지 못했습니다. 단계: " + phase + " 오류 유형: " + type(exc).__name__ + "\n",
        )


if __name__ == "__main__":
    main()
