"""공식 checkpointer와 별도 작업 결과 저널. checkpoint 내부는 수정하지 않는다."""

from contextlib import contextmanager
import json

from backend.errors import InvalidStateError


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
                "이전 작업 호출의 완료 여부를 확인할 수 없습니다. 수정 의견으로 새 실행을 시작해주세요."
            )
        return json.loads(payload)

    def begin(self, task_id):
        self.conn.execute(
            "INSERT INTO workflow_task_results(thread_id,task_id,status,payload) VALUES (%s,%s,'pending','{}') "
            "ON CONFLICT(thread_id,task_id) DO UPDATE SET status='pending',payload='{}'",
            (self.thread_id, task_id),
        )

    def failed(self, task_id):
        self.conn.execute(
            "UPDATE workflow_task_results SET status='failed' WHERE thread_id=%s AND task_id=%s",
            (self.thread_id, task_id),
        )

    def complete(self, task_id, payload):
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
