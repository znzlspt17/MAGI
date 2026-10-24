"""완료 명세와 확정 근거를 내용 해시로 보존한다."""

import hashlib
import json
import re

from backend.errors import InvalidStateError, ArtifactError


def archive_completed(writer, state, content=None):
    content = writer.read_text("final/FINAL_AGENT_SPEC.md") if content is None else content
    data = {"content": content, "basis": {key: value for key, value in state.to_dict().items()
            if key in {"original_user_request", "user_request", "requirement_lock_sheet", "confirmed_user_sources", "revision_history", "reused_decisions"}}}
    if writer.exists("analysis/spec_trace.json"):
        data["trace"] = writer.read_json("analysis/spec_trace.json")
    from backend.services.requirement_review import load_snapshot
    if writer.exists("state/candidate_snapshot.json"):
        try:
            value = writer.read_json("state/candidate_snapshot.json")
            ident = value.get("id") if isinstance(value, dict) else None
        except (OSError, ValueError, UnicodeError, ArtifactError):
            ident = None
        snapshot = load_snapshot(writer, ident, content)
        if snapshot:
            data["review_snapshot_id"] = ident
            if snapshot.get("implementation_plan"):
                data["implementation_plan"] = snapshot["implementation_plan"]
    serialized = json.dumps(data, ensure_ascii=False, sort_keys=True)
    ident = hashlib.sha256(serialized.encode()).hexdigest()
    path = f"completed/{ident}.json"
    if writer.exists(path):
        if writer.read_text(path) != serialized:
            raise InvalidStateError("완료 명세 보존본이 손상되었습니다.")
    else:
        writer.write_text(path, serialized, overwrite=False)
    return {"id": ident, "path": path, "source_hash": hashlib.sha256(content.encode()).hexdigest()}


def completed_references(state):
    paths = list(state.get("created_artifacts", []))
    if isinstance(state.get("latest_completed"), dict):
        paths.append(state["latest_completed"].get("path", ""))
    return list(dict.fromkeys(path for path in paths if isinstance(path, str) and re.fullmatch(r"completed/[0-9a-f]{64}\.json", path)))


def load_completed(writer, ident):
    if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{64}", ident):
        raise InvalidStateError("완료 명세 보존본을 확인할 수 없습니다.")
    serialized = writer.read_text(f"completed/{ident}.json")
    if hashlib.sha256(serialized.encode()).hexdigest() != ident:
        raise InvalidStateError("완료 명세 보존본이 손상되었습니다.")
    data = json.loads(serialized)
    if not isinstance(data.get("content"), str):
        raise InvalidStateError("완료 명세 보존본을 확인할 수 없습니다.")
    return data
