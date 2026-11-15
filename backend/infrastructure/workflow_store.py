"""공식 checkpointer와 별도 작업 결과 저널. checkpoint 내부는 수정하지 않는다."""
from typing import Any

from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
import json

from backend.errors import InvalidStateError, WorkflowPersistenceError
from backend.access.context import AccessError


CURRENT_ATTEMPT: ContextVar[dict[str, Any] | None] = ContextVar("workflow_attempt", default=None)


@contextmanager
def persistence_boundary(message: str, *, passthrough: tuple[type[Exception], ...] = (AccessError,)):
    """2026-11-05: 저장 경계마다 유지해야 할 접근·상태 예외를 명시한다."""
    try:
        yield
    except passthrough:
        raise
    except Exception as exc:
        raise WorkflowPersistenceError(message) from exc


async def provider_entered():
    attempt = CURRENT_ATTEMPT.get()
    if attempt is not None:
        attempt["call_count"] += 1
        with persistence_boundary("Workflow journal progress could not be persisted."):
            await attempt["journal"].progress(attempt["task_id"], attempt["call_count"])


def pending_task(snapshot):
    node = snapshot.next[0] if snapshot.next else ""
    if node == "execute":
        return snapshot.values.get("plan", {}).get("action")
    return {"finalize": "approve", "blocked": "critical_report"}.get(node, node)


async def retry_state(documents):
    """화면과 접수·실행이 같은 checkpoint와 저널 판정을 사용한다."""
    from backend.pipeline.agent_workflow import task_id
    from backend.models import State

    result = {"can_retry": False, "retry_requires_replay": False, "retry_unavailable_reason": ""}
    try:
        snapshot = await documents.workflow_snapshot()
        if not snapshot.values:
            return {**result, "retry_unavailable_reason": "저장된 checkpoint가 없어 다시 시도할 수 없습니다."}
        State.from_workflow_state(snapshot.values)
        if snapshot.values.get("workflow_schema") != 1:
            raise ValueError()
        async with documents.store.transaction(mode="read") as conn:
            conversation = await (await conn.execute(
                "SELECT openai_conversation_state,openai_call_pending FROM jobs WHERE id=%s",
                (documents.job_id,),
            )).fetchone()
        if conversation and conversation["openai_conversation_state"] in {"creating", "initializing"}:
            return {**result, "retry_unavailable_reason": "OpenAI 대화 초기화 완료 여부가 불확실하여 자동 재시도할 수 없습니다."}
        from backend.services.refinement import needs_upgrade
        if any(task.interrupts for task in snapshot.tasks) and needs_upgrade(snapshot.values):
            return {**result, "can_retry": True}
        if any(task.interrupts for task in snapshot.tasks) and snapshot.values.get("status") in {"CRITICAL_BLOCKED", "PASS_PENDING_USER_APPROVAL"} and "retry" in snapshot.values.get("allowed_actions", []):
            return {**result, "can_retry": True}
        if not snapshot.next or any(task.interrupts for task in snapshot.tasks):
            return {**result, "retry_unavailable_reason": "다시 실행할 미완료 단계가 없습니다. 대화에서 다음 요청을 입력하세요."}
        name = pending_task(snapshot)
        if not isinstance(name, str) or not name:
            raise ValueError()
        ident = task_id(snapshot.values, name)
        async with workflow_store(documents.store, documents.job_id) as (_, journal):
            uncertain = name != "approve" and (await journal.status(ident) == "pending"
                                              or bool(conversation and conversation["openai_call_pending"]))
        return {**result, "can_retry": True, "retry_requires_replay": uncertain, "task_id": ident,
                "retry_kind": "mcp" if uncertain and name == "mcp_execute" else "model" if uncertain else "none"}
    except (InvalidStateError, ValueError, TypeError, KeyError):
        return {**result, "retry_unavailable_reason": "저장된 checkpoint 형식이 올바르지 않아 다시 시도할 수 없습니다."}


class TaskJournal:
    def __init__(self, store, thread_id):
        self.store, self.thread_id = store, thread_id

    async def status(self, task_id):
        async with self.store.transaction(mode="read") as conn:
            row = await (await conn.execute(
                "SELECT status FROM workflow.workflow_task_results WHERE thread_id=%s AND task_id=%s",
                (self.thread_id, task_id),
            )).fetchone()
        return row["status"] if row else None

    async def get(self, task_id, *, retry_safe=False):
        async with self.store.transaction(mode="read") as conn:
            row = await (await conn.execute(
                "SELECT status, payload FROM workflow.workflow_task_results WHERE thread_id=%s AND task_id=%s",
                (self.thread_id, task_id),
            )).fetchone()
        if not row:
            return None
        status, payload = (row["status"], row["payload"])
        if status == "failed":
            return None
        if status not in {"completed", "prepared"}:
            if retry_safe:
                return None
            raise InvalidStateError(
                "이전 작업 호출의 완료 여부를 확인할 수 없습니다. 호출 반복 가능성에 동의한 뒤 미완료 단계를 다시 실행하세요."
            )
        result = json.loads(payload)
        if status == "prepared":
            result['_prepared'] = True
        return result

    async def begin(self, task_id):
        async with self.store.transaction() as conn:
            previous = await (await conn.execute(
                "SELECT status,payload FROM workflow.workflow_task_results WHERE thread_id=%s AND task_id=%s FOR UPDATE",
                (self.thread_id, task_id),
            )).fetchone()
            data: dict[str, Any] = {"call_count": 0}
            if previous:
                # 이전 기록은 추정 정산하거나 지우지 않고 새 시도의 감사 정보로 보존한다.
                old = json.loads(previous["payload"])
                history = old.pop("previous_attempts", [])
                data["previous_attempts"] = [*history, {"status": previous["status"], "payload": old}]
            await conn.execute(
                "INSERT INTO workflow.workflow_task_results(thread_id,task_id,status,payload) VALUES (%s,%s,'pending',%s) "
                "ON CONFLICT(thread_id,task_id) DO UPDATE SET status='pending',payload=excluded.payload",
                (self.thread_id, task_id, json.dumps(data)),
            )

    async def progress(self, task_id, count, *, category=None):
        async with self.store.transaction() as conn:
            row = await (await conn.execute("SELECT payload FROM workflow.workflow_task_results WHERE thread_id=%s AND task_id=%s FOR UPDATE",
                                           (self.thread_id, task_id))).fetchone()
            data = json.loads(row["payload"])
            data.update(call_count=count)
            if category:
                data["failure_category"] = category
            await conn.execute("UPDATE workflow.workflow_task_results SET payload=%s WHERE thread_id=%s AND task_id=%s",
                               (json.dumps(data), self.thread_id, task_id))

    async def failed(self, task_id):
        async with self.store.transaction() as conn:
            await conn.execute(
                "UPDATE workflow.workflow_task_results SET status='failed' WHERE thread_id=%s AND task_id=%s",
                (self.thread_id, task_id),
            )

    async def response(self, task_id, response_id):
        async with self.store.transaction() as conn:
            row = await (await conn.execute("SELECT payload FROM workflow.workflow_task_results WHERE thread_id=%s AND task_id=%s FOR UPDATE",
                                           (self.thread_id, task_id))).fetchone()
            data = json.loads(row["payload"])
            data.setdefault("response_ids", []).append(response_id)
            await conn.execute("UPDATE workflow.workflow_task_results SET payload=%s WHERE thread_id=%s AND task_id=%s",
                               (json.dumps(data), self.thread_id, task_id))

    async def complete(self, task_id, payload):
        async with self.store.transaction() as conn:
            row = await (await conn.execute("SELECT payload FROM workflow.workflow_task_results WHERE thread_id=%s AND task_id=%s FOR UPDATE",
                                           (self.thread_id, task_id))).fetchone()
            payload = {**json.loads(row["payload"]), **payload}
            payload.pop('staged_documents', None)
            await conn.execute(
                "UPDATE workflow.workflow_task_results SET status='completed',payload=%s WHERE thread_id=%s AND task_id=%s",
                (json.dumps(payload, ensure_ascii=False), self.thread_id, task_id),
            )

    async def prepare(self, task_id, payload):
        # 2026-11-13: 공개 전 모델 결과와 문서 버전 이력을 보관해 저장 실패 시 중복 호출 없이 재개한다.
        async with self.store.transaction() as conn:
            row = await (await conn.execute("SELECT payload FROM workflow.workflow_task_results WHERE thread_id=%s AND task_id=%s FOR UPDATE",
                                           (self.thread_id, task_id))).fetchone()
            data = {**json.loads(row['payload']), **payload}
            await conn.execute("UPDATE workflow.workflow_task_results SET status='prepared',payload=%s WHERE thread_id=%s AND task_id=%s",
                               (json.dumps(data, ensure_ascii=False), self.thread_id, task_id))


@asynccontextmanager
async def workflow_store(store, thread_id):
    from backend.knowledge.core import checkpoint_store

    async with checkpoint_store(store) as saver:
        yield saver, TaskJournal(store, thread_id)


async def delete_workflow_threads(store, thread_ids):
    """서비스에서 삭제가 승인된 작업만 공식 삭제 API로 제거한다."""
    from backend.knowledge.core import checkpoint_store

    async with checkpoint_store(store) as saver:
        for thread_id in thread_ids:
            await saver.adelete_thread(thread_id)
            async with store.transaction() as conn:
                await conn.execute("DELETE FROM workflow.workflow_task_results WHERE thread_id=%s", (thread_id,))
