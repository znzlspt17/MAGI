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
from backend.knowledge.upgrade import migrate_business, initialize_checkpoints


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
            host="127.0.0.1",
            port=55432,
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
            instance = KnowledgeStore(KnowledgeConfig(config))
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
    saver.setup = lambda: None

    @contextmanager
    def checkpoints(_):
        yield saver

    monkeypatch.setattr("backend.knowledge.core.checkpoint_store", checkpoints)
    yield instance


@pytest.fixture
def legacy_store(empty_store):
    seed_legacy_schema(empty_store)
    return empty_store


@pytest.fixture
def store(legacy_store):
    migrate_business(legacy_store)
    initialize_checkpoints(legacy_store)
    if os.environ.get("CI") == "true" and os.environ.get("CI_POSTGRES") == "1":
        from backend.knowledge.upgrade import verify_and_enable

        with legacy_store.transaction() as conn:
            if not conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname='ci_service'"
            ).fetchone():
                conn.execute(
                    "CREATE ROLE ci_service LOGIN PASSWORD 'ci-only' NOSUPERUSER NOBYPASSRLS"
                )
        verify_and_enable(legacy_store, application_role="ci_service")
        return KnowledgeStore(
            KnowledgeConfig({**legacy_store.config.connection, "user": "ci_service"})
        )
    return legacy_store


def seed_legacy_schema(store):
    with store.transaction(mode="maintenance") as conn:
        conn.execute("SET LOCAL search_path TO public")
        conn.execute(
            "SELECT set_config('magi.internal','on',true),set_config('app.internal','on',true)"
        )
        conn.execute("CREATE TABLE magi_schema_versions(version text PRIMARY KEY)")
        for index in range(1, 12):
            name = f"{index:03}.sql"
            conn.execute(
                Path(__file__)
                .with_name("fixtures")
                .joinpath("legacy_schema", name)
                .read_text(encoding="utf-8")
            )
            table = "schema_versions" if index >= 9 else "magi_schema_versions"
            conn.execute(f"INSERT INTO {table}(version) VALUES (%s)", (name,))
