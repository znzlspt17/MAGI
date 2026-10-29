"""공식 checkpointer와 별도 작업 결과 저널. checkpoint 내부는 수정하지 않는다."""

from contextlib import contextmanager
from contextvars import ContextVar
import json

from backend.errors import InvalidStateError


CURRENT_ATTEMPT = ContextVar("workflow_attempt", default=None)


def provider_entered():
    attempt = CURRENT_ATTEMPT.get()
    if attempt is not None:
        attempt["call_count"] += 1
        attempt["journal"].progress(attempt["task_id"], attempt["call_count"])


def pending_task(snapshot):
    node = snapshot.next[0] if snapshot.next else ""
    if node == "execute":
        return snapshot.values.get("plan", {}).get("action")
    return {"finalize": "approve", "blocked": "critical_report"}.get(node, node)


def retry_state(documents):
    """화면과 접수·실행이 같은 checkpoint와 저널 판정을 사용한다."""
    from backend.pipeline.agent_workflow import task_id
    from backend.models import State

    result = {"can_retry": False, "retry_requires_replay": False, "retry_unavailable_reason": ""}
    try:
        snapshot = documents.workflow_snapshot()
        if not snapshot.values:
            return {**result, "retry_unavailable_reason": "저장된 checkpoint가 없어 다시 시도할 수 없습니다."}
        State.from_workflow_state(snapshot.values)
        if snapshot.values.get("workflow_schema") != 1:
            raise ValueError()
        with documents.store.transaction(mode="read") as conn:
            conversation = conn.execute(
                "SELECT openai_conversation_state,openai_call_pending FROM jobs WHERE id=%s",
                (documents.job_id,),
            ).fetchone()
        if conversation and conversation["openai_conversation_state"] in {"creating", "initializing"}:
            return {**result, "retry_unavailable_reason": "OpenAI 대화 초기화 완료 여부가 불확실하여 자동 재시도할 수 없습니다."}
        if any(task.interrupts for task in snapshot.tasks) and snapshot.values.get("status") == "CRITICAL_BLOCKED" and "retry" in snapshot.values.get("allowed_actions", []):
            return {**result, "can_retry": True}
        if not snapshot.next or any(task.interrupts for task in snapshot.tasks):
            return {**result, "retry_unavailable_reason": "다시 실행할 미완료 단계가 없습니다. 대화에서 다음 요청을 입력하세요."}
        name = pending_task(snapshot)
        if not isinstance(name, str) or not name:
            raise ValueError()
        ident = task_id(snapshot.values, name)
        with workflow_store(documents.store, documents.job_id) as (_, journal):
            uncertain = name != "approve" and (journal.status(ident) == "pending"
                                              or bool(conversation and conversation["openai_call_pending"]))
        return {**result, "can_retry": True, "retry_requires_replay": uncertain, "task_id": ident}
    except (InvalidStateError, ValueError, TypeError, KeyError):
        return {**result, "retry_unavailable_reason": "저장된 checkpoint 형식이 올바르지 않아 다시 시도할 수 없습니다."}


class TaskJournal:
    def __init__(self, conn, thread_id):
        self.conn, self.thread_id = conn, thread_id

    def status(self, task_id):
        row = self.conn.execute(
            "SELECT status FROM workflow_task_results WHERE thread_id=%s AND task_id=%s",
            (self.thread_id, task_id),
        ).fetchone()
        return row["status"] if row else None

    def get(self, task_id, *, retry_safe=False):
        row = self.conn.execute(
            "SELECT status, payload FROM workflow_task_results WHERE thread_id=%s AND task_id=%s",
            (self.thread_id, task_id),
        ).fetchone()
        if not row:
            return None
        status, payload = (row["status"], row["payload"])
        if status == "failed":
            return None
        if status != "completed":
            if retry_safe:
                return None
            raise InvalidStateError(
                "이전 작업 호출의 완료 여부를 확인할 수 없습니다. 호출 반복 가능성에 동의한 뒤 미완료 단계를 다시 실행하세요."
            )
        return json.loads(payload)

    def begin(self, task_id):
        previous = self.conn.execute(
            "SELECT status,payload FROM workflow_task_results WHERE thread_id=%s AND task_id=%s",
            (self.thread_id,task_id),
        ).fetchone()
        data = {"call_count": 0}
        if previous:
            # 이전 기록은 추정 정산하거나 지우지 않고 새 시도의 감사 정보로 보존한다.
            old = json.loads(previous["payload"])
            history = old.pop("previous_attempts", [])
            data["previous_attempts"] = [*history, {"status": previous["status"], "payload": old}]
        self.conn.execute(
            "INSERT INTO workflow_task_results(thread_id,task_id,status,payload) VALUES (%s,%s,'pending',%s) "
            "ON CONFLICT(thread_id,task_id) DO UPDATE SET status='pending',payload=excluded.payload",
            (self.thread_id, task_id,json.dumps(data)),
        )

    def progress(self, task_id, count, *, category=None):
        row = self.conn.execute("SELECT payload FROM workflow_task_results WHERE thread_id=%s AND task_id=%s",
                                (self.thread_id,task_id)).fetchone()
        data = json.loads(row["payload"])
        data.update(call_count=count)
        if category:
            data["failure_category"] = category
        self.conn.execute("UPDATE workflow_task_results SET payload=%s WHERE thread_id=%s AND task_id=%s",
                          (json.dumps(data),self.thread_id,task_id))

    def failed(self, task_id):
        self.conn.execute(
            "UPDATE workflow_task_results SET status='failed' WHERE thread_id=%s AND task_id=%s",
            (self.thread_id, task_id),
        )

    def response(self, task_id, response_id):
        row = self.conn.execute("SELECT payload FROM workflow_task_results WHERE thread_id=%s AND task_id=%s",
                                (self.thread_id, task_id)).fetchone()
        data = json.loads(row["payload"])
        data.setdefault("response_ids", []).append(response_id)
        self.conn.execute("UPDATE workflow_task_results SET payload=%s WHERE thread_id=%s AND task_id=%s",
                          (json.dumps(data), self.thread_id, task_id))

    def complete(self, task_id, payload):
        row = self.conn.execute("SELECT payload FROM workflow_task_results WHERE thread_id=%s AND task_id=%s",
                                (self.thread_id,task_id)).fetchone()
        payload = {**json.loads(row["payload"]), **payload}
        self.conn.execute(
            "UPDATE workflow_task_results SET status='completed',payload=%s WHERE thread_id=%s AND task_id=%s",
            (json.dumps(payload, ensure_ascii=False), self.thread_id, task_id),
        )


@contextmanager
def workflow_store(store, thread_id):
    from backend.knowledge.core import checkpoint_store

    with checkpoint_store(store) as saver:
        yield saver, TaskJournal(saver.conn, thread_id)


def delete_workflow_threads(store, thread_ids):
    """서비스에서 삭제가 승인된 작업만 공식 삭제 API로 제거한다."""
    from backend.knowledge.core import checkpoint_store

    with checkpoint_store(store) as saver:
        for thread_id in thread_ids:
            saver.delete_thread(thread_id)
            saver.conn.execute(
                "DELETE FROM workflow_task_results WHERE thread_id=%s", (thread_id,)
            )
