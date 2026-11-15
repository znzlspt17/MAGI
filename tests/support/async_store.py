"""실제 psycopg 비동기 연결을 사용하는 격리 테스트 저장소."""

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from uuid import uuid4

import pytest

from backend.knowledge.config import KnowledgeConfig, KnowledgeError
from backend.knowledge.setup import load_migrations
from backend.knowledge.store import KnowledgeStore


@asynccontextmanager
async def isolated_async_store(*, initialized=True):
    """2026-11-13: 테스트마다 별도 DB 또는 별도 WASM 프로세스를 사용한다."""
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    process = None
    dbname = None
    admin = None
    store = None
    ci_postgres = os.environ.get("CI") == "true" and os.environ.get("CI_POSTGRES") == "1"
    if ci_postgres:
        base = {"host": os.environ.get("TEST_POSTGRES_HOST", "127.0.0.1"),
                "port": int(os.environ.get("TEST_POSTGRES_PORT", "55432")),
                "dbname": "postgres", "user": "postgres", "password": "ci-only", "connect_timeout": 3}
        dbname = "magi_test_" + uuid4().hex
        admin = await psycopg.AsyncConnection.connect(**base, autocommit=True)
        await admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
        config = {**base, "dbname": dbname}
    else:
        runtime = Path(os.environ.get("TEST_PGLITE_RUNTIME", str(Path(tempfile.gettempdir()) / "knowledge-validation")))
        if not shutil.which("node") or not (runtime / "node_modules/@electric-sql/pglite-socket").is_dir():
            pytest.skip("독립 테스트용 PGlite socket 런타임이 설치되지 않았습니다.")
        script = Path(__file__).with_name("pglite_socket.mjs")
        process = subprocess.Popen(
            ["node", str(script), str(runtime)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        line = await asyncio.to_thread(process.stdout.readline)
        if not line:
            raise RuntimeError("테스트 DB 소켓을 시작하지 못했습니다.")
        port = int(json.loads(line)["address"].rsplit(":", 1)[1])
        config = {"host": "127.0.0.1", "port": port, "dbname": "postgres",
                  "user": "ci_service", "password": "ci-only", "sslmode": "disable",
                  "prepare_threshold": None}

    try:
        conn = await psycopg.AsyncConnection.connect(**config, autocommit=True, row_factory=dict_row)
        try:
            if ci_postgres:
                await conn.execute("CREATE EXTENSION vector")
                found = await (await conn.execute("SELECT 1 FROM pg_roles WHERE rolname='ci_service'")).fetchone()
                if not found:
                    await conn.execute("CREATE ROLE ci_service LOGIN PASSWORD 'ci-only' NOSUPERUSER NOBYPASSRLS")
                await conn.execute(sql.SQL("GRANT CREATE ON DATABASE {} TO ci_service").format(sql.Identifier(dbname)))
                await conn.execute("GRANT USAGE,CREATE ON SCHEMA public TO ci_service")
            await conn.execute("SET ROLE ci_service")
            if initialized:
                async with conn.transaction():
                    await conn.execute("CREATE TABLE public.schema_migrations(version integer PRIMARY KEY,checksum text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())")
                    for migration in load_migrations():
                        await conn.execute("SET LOCAL search_path TO public")
                        await conn.execute(migration.sql, prepare=False)
                        await conn.execute("INSERT INTO public.schema_migrations(version,checksum) VALUES (%s,%s)",
                                           (migration.version, migration.checksum))
        finally:
            await conn.close()

        store = KnowledgeStore(KnowledgeConfig({**config, "user": "ci_service"}))
        async def configure(conn):
            await conn.execute("SET ROLE ci_service")
            await conn.execute("SET search_path TO workflow, public")
        # 2026-11-15: PGlite socket은 하나의 DB backend를 공유하므로 wire 세션을 직렬화한다.
        # 실제 PostgreSQL은 독립 연결의 동시성을 그대로 검증한다.
        pool = AsyncConnectionPool(conninfo="", kwargs={**store.config.connection, "autocommit": True, "row_factory": dict_row},
                                   min_size=0, max_size=8 if ci_postgres else 1, open=False, configure=configure)
        await pool.open()
        store._async_pool = pool
        if initialized:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            await AsyncPostgresSaver(pool).setup()

        @asynccontextmanager
        async def admin_transaction():
            # 2026-11-13: 권한 검사는 격리 테스트 DB의 관리 세션에서만 수행한다.
            params = {**config, "user": "postgres"} if ci_postgres else config
            connection = await psycopg.AsyncConnection.connect(**params, autocommit=True, row_factory=dict_row)
            try:
                if not ci_postgres:
                    await connection.execute("RESET ROLE")
                try:
                    async with connection.transaction():
                        yield connection
                except psycopg.Error as exc:
                    raise KnowledgeError("테스트 DB 관리 작업에 실패했습니다.") from exc
            finally:
                if not ci_postgres:
                    await connection.execute("SET ROLE ci_service")
                await connection.close()

        store.test_admin_transaction = admin_transaction
        yield store
    finally:
        if store is not None:
            await store.close_async()
        if process is not None:
            process.stdin.close()
            try:
                await asyncio.to_thread(process.wait, timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                await asyncio.to_thread(process.wait, timeout=5)
        if admin is not None:
            try:
                if dbname is not None:
                    await admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(dbname)))
            finally:
                await admin.close()
