"""명시적 이관과 로컬 임베딩 재생성 명령."""

import argparse
import json
import re
from pathlib import Path

from backend.errors import InvalidStateError
from backend.models import RequirementLockSheet
from backend.knowledge.config import KnowledgeConfig, KnowledgeError, load_environment
from backend.knowledge.projection import digest
from backend.knowledge.runtime import KnowledgeService, read_artifacts
from backend.knowledge.store import KnowledgeStore


def import_legacy(data_dir, store=None):
    """store 없이 호출하면 어떤 설정과 DB에도 접근하지 않는 미리보기다."""
    from backend.knowledge.format_guard import require_current
    require_current(data_dir)
    root = Path(data_dir).resolve()
    results = []
    existing = {item["id"] for item in store.jobs()} if store is not None else set()
    for folder in sorted(root.iterdir()):
        if not re.fullmatch(r"[0-9a-f]{32}", folder.name) or not folder.is_dir() or folder.is_symlink():
            continue
        job_path = folder / "job.json"
        if not job_path.is_file() or job_path.is_symlink():
            continue
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
            if job.get("id") != folder.name or not isinstance(job.get("request"), str):
                continue
            artifacts = read_artifacts(folder)
            state = json.loads(artifacts.get("state/state.json", "{}"))
            state.setdefault("user_request", job["request"])
            sheet = state.get("requirement_lock_sheet")
            if sheet is not None:
                RequirementLockSheet.from_dict(sheet)
            elif "analysis/requirement_lock_sheet.json" in artifacts:
                RequirementLockSheet.from_dict(json.loads(artifacts["analysis/requirement_lock_sheet.json"]))
            if store is not None:
                if job["id"] in existing:
                    # DB로 운영된 작업을 낡은 파일 상태로 되돌리지 않는다.
                    results.append({"job_id": job["id"], "status": "already_imported"})
                    continue
                project_id = digest(["legacy", job["id"]])[:32]
                store.create_project(job["request"][:80] or "이전 작업", project_id)
                job["project_id"] = project_id
                job.setdefault("provider", "openai")
                job.setdefault("demo", False)
                state["import_origin"] = {"provider": job["provider"], "demo": job["demo"]}
                store.commit_stage(job, digest(["import", job["id"]]), "import", state, artifacts)
            results.append({"job_id": job["id"], "artifact_count": len(artifacts), "status": "imported" if store else "preview"})
        except InvalidStateError:
            results.append({"job_id": folder.name, "status": "unsupported_contract"})
        except (ValueError, TypeError, KeyError):
            results.append({"job_id": folder.name, "status": "invalid"})
    return results


def main():
    parser = argparse.ArgumentParser(description="지식 저장소 관리")
    sub = parser.add_subparsers(dest="command", required=True)
    legacy = sub.add_parser("import", help="기존 작업 미리보기; --apply로 DB에 이관")
    legacy.add_argument("--data-dir", default="web_data")
    legacy.add_argument("--apply", action="store_true")
    sub.add_parser("migrate", help="DB 스키마 생성·갱신")
    sub.add_parser("reindex", help="설정된 로컬 모델로 임베딩 재생성·재시도")
    args = parser.parse_args()
    try:
        if args.command == "import" and not args.apply:
            result = import_legacy(args.data_dir)
        else:
            load_environment()
            config = KnowledgeConfig.from_env()
            if config is None:
                raise KnowledgeError("DB 설정이 필요합니다.")
            store = KnowledgeStore(config)
            store.migrate()
            if args.command == "import":
                result = import_legacy(args.data_dir, store)
            elif args.command == "reindex":
                service = KnowledgeService(store)
                try:
                    if not service.reindex():
                        raise KnowledgeError(service.last_error)
                    result = {"status": "completed"}
                finally:
                    service.close()
            else:
                result = {"status": "completed"}
        print(json.dumps(result, ensure_ascii=True))
    except (KnowledgeError, OSError):
        parser.exit(1, "저장소 작업을 완료하지 못했습니다. 설정·연결·파일 형식을 확인하세요.\n")


if __name__ == "__main__":
    main()
