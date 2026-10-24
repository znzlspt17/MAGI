"""보호 설정을 읽지 않는 전용 검증 DB. CI는 실제 PostgreSQL, 로컬은 WASM SQL 검증이다."""

import json
import os
from decimal import Decimal
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from uuid import uuid4
import pytest
from backend.knowledge.config import KnowledgeConfig, KnowledgeError
from backend.knowledge.store import KnowledgeStore
from backend.knowledge.setup import migrate
from backend.access.runtime import PublicRuntime


@pytest.fixture
def wasm_connection():
    runtime = Path(
        os.environ.get(
            "TEST_PGLITE_RUNTIME",
            str(Path(tempfile.gettempdir()) / "knowledge-validation"),
        )
    )
    if (
        not shutil.which("node")
        or not (runtime / "node_modules/@electric-sql/pglite-pgvector").is_dir()
    ):
        pytest.skip("별도 테스트용 PGlite+pgvector 런타임이 설치되지 않았습니다.")
    process = subprocess.Popen(
        ["node", str(Path(__file__).with_name("pglite_bridge.mjs")), str(runtime)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert json.loads(process.stdout.readline())["ready"]

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def fetchone(self):
            return self.rows[0] if self.rows else None

        def fetchall(self):
            return self.rows

    connection_gate = threading.RLock()

    class Connection:
        def execute(self, sql, params=()):
            if not isinstance(sql, str):
                sql = sql.as_string()
            count = iter(range(1, 1000))
            for _ in params:
                sql = sql.replace("%s", "$" + str(next(count)), 1)
            params = [value.obj if hasattr(value, "obj") else value for value in params]
            params = [
                str(value) if isinstance(value, Decimal) else value for value in params
            ]
            process.stdin.write(
                json.dumps({"sql": sql, "params": params}, ensure_ascii=False) + "\n"
            )
            process.stdin.flush()
            response = json.loads(process.stdout.readline())
            if "error" in response:
                raise KnowledgeError(response["error"])
            for row in response["rows"]:
                if "total" in row:
                    row["total"] = int(row["total"])
            return Result(response["rows"])

        def commit(self):
            pass

        def close(self):
            self.execute("SELECT pg_advisory_unlock_all()")

        def __enter__(self):
            connection_gate.acquire()
            try:
                self.execute("BEGIN")
                return self
            except Exception:
                connection_gate.release()
                raise

        def __exit__(self, typ, value, tb):
            try:
                self.execute("ROLLBACK" if typ else "COMMIT")
            finally:
                connection_gate.release()

    instance = KnowledgeStore(KnowledgeConfig({}), connect=lambda **kw: Connection())
    bootstrap = instance.connect()
    bootstrap.execute("CREATE ROLE ci_service NOSUPERUSER NOBYPASSRLS")
    bootstrap.execute("GRANT USAGE,CREATE ON SCHEMA public TO ci_service")
    bootstrap.execute("DO $$ BEGIN EXECUTE format('GRANT CREATE ON DATABASE %I TO ci_service', current_database()); END $$")
    bootstrap.execute("SET ROLE ci_service")
    try:
        yield instance
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)


@pytest.fixture
def empty_store(request, monkeypatch):
    if os.environ.get("CI") == "true" and os.environ.get("CI_POSTGRES") == "1":
        import psycopg
        from psycopg import sql

        connection = dict(
            host=os.environ.get("TEST_POSTGRES_HOST", "127.0.0.1"),
            port=int(os.environ.get("TEST_POSTGRES_PORT", "55432")),
            dbname="postgres",
            user="postgres",
            password="ci-only",
            connect_timeout=3,
        )
        database = "magi_test_" + uuid4().hex
        with psycopg.connect(**connection, autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database))
            )
        try:
            config = {**connection, "dbname": database}
            with psycopg.connect(**config) as admin:
                admin.execute("CREATE EXTENSION vector")
                if not admin.execute("SELECT 1 FROM pg_roles WHERE rolname='ci_service'").fetchone():
                    admin.execute("CREATE ROLE ci_service LOGIN PASSWORD 'ci-only' NOSUPERUSER NOBYPASSRLS")
                admin.execute(sql.SQL("GRANT CREATE ON DATABASE {} TO ci_service").format(sql.Identifier(database)))
                admin.execute("GRANT USAGE,CREATE ON SCHEMA public TO ci_service")
            instance = KnowledgeStore(KnowledgeConfig({**config, "user": "ci_service"}))
            yield instance
        finally:
            with psycopg.connect(**connection, autocommit=True) as admin:
                admin.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        sql.Identifier(database)
                    )
                )
        return
    instance = request.getfixturevalue("wasm_connection")
    from langgraph.checkpoint.memory import InMemorySaver

    saver = InMemorySaver()
    saver.conn = instance.connect()
    def setup_checkpoints():
        from langgraph.checkpoint.postgres.base import MIGRATIONS

        saver.conn.execute("SET search_path TO workflow,public")
        saver.conn.execute(MIGRATIONS[0])
        row = saver.conn.execute("SELECT max(v) AS version FROM checkpoint_migrations").fetchone()
        previous = row["version"] if row["version"] is not None else -1
        for version, statement in enumerate(MIGRATIONS):
            if version > previous:
                saver.conn.execute(statement.replace("INDEX CONCURRENTLY", "INDEX"))
                saver.conn.execute("INSERT INTO checkpoint_migrations(v) VALUES (%s)", (version,))

    saver.setup = setup_checkpoints

    @contextmanager
    def checkpoints(_):
        yield saver

    monkeypatch.setattr("backend.knowledge.core.checkpoint_store", checkpoints)
    yield instance


@pytest.fixture
def store(empty_store):
    runtime = PublicRuntime(empty_store)
    try:
        runtime.acquire(recover=False)
        migrate(empty_store, runtime=runtime)
    finally:
        runtime.close()
    return empty_store


@pytest.fixture
def admin_transaction(empty_store):
    """테스트 역할 생성·권한 변경만 별도의 관리자 경로에서 실행한다."""
    @contextmanager
    def transaction():
        if empty_store.config.connection:
            admin = KnowledgeStore(KnowledgeConfig({**empty_store.config.connection, "user": "postgres"}))
            with admin.transaction() as conn:
                yield conn
        else:
            bootstrap = empty_store.connect()
            bootstrap.execute("RESET ROLE")
            try:
                with empty_store.transaction() as conn:
                    yield conn
            finally:
                bootstrap.execute("SET ROLE ci_service")

    return transaction
