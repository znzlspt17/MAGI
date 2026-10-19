"""완료 명세와 확정 근거를 내용 해시로 보존한다."""

import hashlib
import json
import re

from backend.errors import InvalidStateError


def archive_completed(writer, state, content=None):
    content = writer.read_text("final/FINAL_AGENT_SPEC.md") if content is None else content
    data = {"content": content, "basis": {key: value for key, value in state.to_dict().items()
            if key in {"original_user_request", "user_request", "requirement_lock_sheet", "confirmed_user_sources", "revision_history"}}}
    trace = writer.path("analysis/spec_trace.json")
    if trace.is_file():
        data["trace"] = writer.read_json("analysis/spec_trace.json")
    serialized = json.dumps(data, ensure_ascii=False, sort_keys=True)
    ident = hashlib.sha256(serialized.encode()).hexdigest()
    path = f"completed/{ident}.json"
    target = writer.path(path)
    if target.exists():
        if target.read_text(encoding="utf-8") != serialized:
            raise InvalidStateError("완료 명세 보존본이 손상되었습니다.")
    else:
        writer.write_text(path, serialized, overwrite=False)
    return {"id": ident, "path": path, "source_hash": hashlib.sha256(content.encode()).hexdigest()}


def require_conversation(writer):
    from backend.infrastructure.conversation_state import ConversationState
    from backend.errors import ConversationUnavailableError
    conversation = ConversationState(writer)
    if not conversation.conversation_id:
        raise ConversationUnavailableError("Conversation state is missing. Start a new generation.")
    return conversation


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


def restore_completed_cache(writer, state):
    """대표 파일은 저장된 완료 포인터를 기준으로 복구할 수 있는 캐시다."""
    reference = state.latest_completed
    if not reference:
        return
    path = reference.get("path", "")
    if not isinstance(path, str) or not re.fullmatch(r"completed/[0-9a-f]{64}\.json", path):
        raise InvalidStateError("완료 명세 보존본을 확인할 수 없습니다.")
    if path != f"completed/{reference.get('id')}.json":
        raise InvalidStateError("완료 명세 보존본이 손상되었습니다.")
    data = load_completed(writer, reference.get("id"))
    target = writer.path("final/FINAL_AGENT_SPEC.md")
    if not target.exists() or target.read_text(encoding="utf-8") != data["content"]:
        import os
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = writer.path("final/FINAL_AGENT_SPEC.tmp")
        temporary.write_text(data["content"], encoding="utf-8")
        os.replace(temporary, target)
