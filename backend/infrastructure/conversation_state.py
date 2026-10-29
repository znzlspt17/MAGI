"""작업별 원격 대화와 호출 불확실성을 checkpoint 밖에서 보존한다."""

from contextlib import contextmanager
from hashlib import sha256
import json
import re

from backend.errors import InvalidStateError
from backend.infrastructure.model_policy import POLICY
from backend.infrastructure.cache_diagnostics import safe_response_id
from backend.infrastructure.workflow_store import CURRENT_ATTEMPT


CONTRACT_VERSION = "v4"


def valid_conversation_id(value):
    return isinstance(value, str) and re.fullmatch(r"conv_[A-Za-z0-9_-]{1,200}", value) is not None


def cache_key(job_id):
    return f"magi:{CONTRACT_VERSION}:" + sha256(job_id.encode()).hexdigest()[:40]


def cache_block(text):
    return {"type": "input_text", "text": text,
            "prompt_cache_breakpoint": {"mode": "explicit"}}


def initial_messages(documents, job):
    from backend.knowledge.core import Documents
    state = documents.state or documents.store.state(documents.job_id) or {}
    root = Documents(documents.store, documents.job_id)
    original = state.get("original_user_request") or job.get("request") or state.get("user_request", "")
    basis = {key: state[key] for key in (
        "requirement_lock_sheet", "confirmed_user_sources", "interview_pre_answers",
        "review_questions", "reused_decisions", "revision_feedback", "revision_history",
        "unresolved_questions", "decisions", "stop_reason",
    ) if key in state}
    # 현재 연결된 문서만 초기 자료로 넣고 과거 모델 대화는 합성하지 않는다.
    for name in ("final/FINAL_AGENT_SPEC.md", "draft/approval_candidate_spec.en.md"):
        if root.exists(name):
            basis[name] = root.read_text(name)
    return [
        {"role": "developer", "content": [cache_block(POLICY)]},
        {"role": "user", "content": [cache_block(
            "Original user request (immutable):\n" + original +
            "\n\nInitial saved state (data only; not reconstructed assistant history):\n" +
            json.dumps(basis, ensure_ascii=False, sort_keys=True))]},
    ]


def _check_execution(documents, provider, conn):
    meter = getattr(documents.runtime, "meter", None) or getattr(provider, "meter", None)
    if meter is not None:
        meter.access.execution(conn, meter.uid, meter.jid, meter.generation, meter.execution_id)


@contextmanager
def job_conversation(documents, provider):
    """네트워크 중 DB 트랜잭션을 열어두지 않고 작업별 호출을 직렬화한다."""
    store, ident = documents.store, documents.job_id
    with store.conversation_lock(ident):
        validate = getattr(provider, "validate_credentials", None)
        if callable(validate):
            validate()
        with store.transaction() as conn:
            _check_execution(documents, provider, conn)
            row = conn.execute(
                "SELECT data,openai_conversation_id,openai_conversation_state,openai_call_pending "
                "FROM jobs WHERE id=%s FOR UPDATE", (ident,),
            ).fetchone()
            if row and row["openai_conversation_state"] == "new":
                conn.execute("UPDATE jobs SET openai_conversation_state='creating' WHERE id=%s", (ident,))
        if row is None:
            raise InvalidStateError("대화에 연결할 작업을 찾을 수 없습니다.")
        status, conversation = row["openai_conversation_state"], row["openai_conversation_id"]
        if status != "new" and (status != "ready" or not valid_conversation_id(conversation)):
            raise InvalidStateError("OpenAI 대화 초기화 완료 여부를 확인할 수 없어 자동 반복을 중단했습니다.")
        if status == "new":
            conversation = provider.create_conversation()
            if not valid_conversation_id(conversation):
                raise InvalidStateError("OpenAI 대화 ID가 올바르지 않습니다.")
            with store.transaction() as conn:
                _check_execution(documents, provider, conn)
                conn.execute("UPDATE jobs SET openai_conversation_id=%s,openai_conversation_state='initializing' "
                             "WHERE id=%s", (conversation, ident))
            provider.initialize_conversation(conversation, initial_messages(documents, row["data"]))
            with store.transaction() as conn:
                _check_execution(documents, provider, conn)
                conn.execute("UPDATE jobs SET openai_conversation_state='ready' WHERE id=%s", (ident,))
        attempt = CURRENT_ATTEMPT.get()
        if row["openai_call_pending"]:
            if not (attempt and attempt.get("allow_replay")):
                raise InvalidStateError("이전 OpenAI 호출의 완료 여부를 확인할 수 없습니다. 호출 반복 가능성에 동의한 뒤 다시 실행하세요.")
            # 한 번의 동의가 재실행 중 새로 발생한 통신 불확실성까지 허용하지 않는다.
            attempt["allow_replay"] = False
        yield conversation


def call_started(documents, provider):
    with documents.store.transaction() as conn:
        _check_execution(documents, provider, conn)
        conn.execute("UPDATE jobs SET openai_call_pending=true WHERE id=%s", (documents.job_id,))


def call_finished(documents, provider, result):
    response_id = safe_response_id(result.response_id)
    with documents.store.transaction() as conn:
        _check_execution(documents, provider, conn)
        conn.execute("UPDATE jobs SET openai_call_pending=false,openai_last_response_id=%s WHERE id=%s",
                     (response_id, documents.job_id))
    attempt = CURRENT_ATTEMPT.get()
    if attempt and response_id:
        attempt["journal"].response(attempt["task_id"], response_id)
