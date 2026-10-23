"""공식 checkpointer와 별도 작업 결과 저널. checkpoint 내부는 수정하지 않는다."""

from contextlib import contextmanager, closing
import json
import sqlite3

from backend.errors import InvalidStateError


class TaskJournal:
    def __init__(self, conn, thread_id, *, postgres=False):
        self.conn, self.thread_id, self.postgres = conn, thread_id, postgres

    def execute(self, query, params=()):
        return self.conn.execute(query.replace("?", "%s") if self.postgres else query, params)

    def status(self, task_id):
        row = self.execute("SELECT status FROM workflow_task_results WHERE thread_id=? AND task_id=?",
                           (self.thread_id, task_id)).fetchone()
        return (row["status"] if self.postgres else row[0]) if row else None

    def get(self, task_id, *, retry_safe=False):
        row = self.execute("SELECT status, payload FROM workflow_task_results WHERE thread_id=? AND task_id=?",
                           (self.thread_id, task_id)).fetchone()
        if not row:
            return None
        status, payload = (row["status"], row["payload"]) if self.postgres else row
        if status == "failed":
            return None
        if status != "completed":
            if retry_safe:
                return None
            raise InvalidStateError("이전 작업 호출의 완료 여부를 확인할 수 없습니다. 수정 의견으로 새 실행을 시작해주세요.")
        return json.loads(payload)

    def begin(self, task_id):
        self.execute("INSERT INTO workflow_task_results(thread_id,task_id,status,payload) VALUES (?,?,'pending','{}') "
                     "ON CONFLICT(thread_id,task_id) DO UPDATE SET status='pending',payload='{}'",
                     (self.thread_id, task_id))
        if not self.postgres:
            self.conn.commit()

    def failed(self, task_id):
        self.execute("UPDATE workflow_task_results SET status='failed' WHERE thread_id=? AND task_id=?",
                     (self.thread_id, task_id))
        if not self.postgres:
            self.conn.commit()

    def complete(self, task_id, payload):
        self.execute("UPDATE workflow_task_results SET status='completed',payload=? WHERE thread_id=? AND task_id=?",
                     (json.dumps(payload, ensure_ascii=False), self.thread_id, task_id))
        if not self.postgres:
            self.conn.commit()


@contextmanager
def workflow_store(writer, thread_id):
    from backend.knowledge.runtime import CURRENT
    runtime = CURRENT.get()
    if runtime is not None:
        from langgraph.checkpoint.postgres import PostgresSaver
        import psycopg
        from psycopg.rows import dict_row
        # 서비스가 보유한 접속 설정만 전달한다. 호출 인자나 로그로 직렬화하지 않는다.
        with psycopg.connect(**runtime.service.store.config.connection, autocommit=True,
                             row_factory=dict_row) as conn:
            conn.execute("SELECT pg_advisory_lock(72410639)")
            try:
                conn.execute("CREATE SCHEMA IF NOT EXISTS magi_workflow")
                conn.execute("SET search_path TO magi_workflow")
                saver = PostgresSaver(conn)
                saver.setup()
                conn.execute("CREATE TABLE IF NOT EXISTS workflow_task_results (thread_id text NOT NULL, "
                             "task_id text NOT NULL, status text NOT NULL, payload text NOT NULL, "
                             "PRIMARY KEY(thread_id,task_id))")
            finally:
                conn.execute("SELECT pg_advisory_unlock(72410639)")
            yield saver, TaskJournal(conn, thread_id, postgres=True)
    else:
        with sqlite_workflow_store(writer, thread_id) as storage:
            yield storage


@contextmanager
def sqlite_workflow_store(writer, thread_id):
    from langgraph.checkpoint.sqlite import SqliteSaver
    path = writer.path("state/workflow.sqlite")
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(path), check_same_thread=False)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS workflow_task_results (thread_id text NOT NULL, "
                     "task_id text NOT NULL, status text NOT NULL, payload text NOT NULL, "
                     "PRIMARY KEY(thread_id,task_id))")
        conn.commit()
        saver = SqliteSaver(conn)
        saver.setup()
        yield saver, TaskJournal(conn, thread_id)

def delete_workflow_threads(store, thread_ids):
    """서비스에서 삭제가 승인된 작업만 공식 삭제 API로 제거한다."""
    from langgraph.checkpoint.postgres import PostgresSaver
    import psycopg
    from psycopg.rows import dict_row
    with store.transaction(mode="read") as check:
        exists = check.execute("SELECT to_regclass('magi_workflow.checkpoints') AS name").fetchone()
        if not exists["name"]:
            return
    with psycopg.connect(**store.config.connection, autocommit=True, row_factory=dict_row) as conn:
        conn.execute("SET search_path TO magi_workflow")
        saver = PostgresSaver(conn)
        for thread_id in thread_ids:
            saver.delete_thread(thread_id)
            conn.execute("DELETE FROM workflow_task_results WHERE thread_id=%s", (thread_id,))
