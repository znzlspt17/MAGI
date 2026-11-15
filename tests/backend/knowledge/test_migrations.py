"""번호별 SQL 적용·롤백·불변 이력과 checkpoint 준비 재시도를 검증한다."""

from contextlib import asynccontextmanager
from functools import wraps
import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock

import pytest

from backend.access.runtime import PublicRuntime
from backend.errors import InvalidStateError
from backend.knowledge import setup
from backend.knowledge.config import KnowledgeConfig
from backend.knowledge.store import KnowledgeStore


def async_test(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
        with asyncio.Runner(loop_factory=factory) as runner:
            return runner.run(function(*args, **kwargs))
    return wrapped


VERSION = len(setup.load_migrations())
NEXT = f"{VERSION + 1:03d}.sql"


async def prepare(store):
    runtime = PublicRuntime(store)
    try:
        (await runtime.acquire(recover=False))
        return (await setup.migrate(store, runtime=runtime))
    finally:
        (await runtime.close())


@pytest.fixture
def migration_files(tmp_path, monkeypatch):
    directory = tmp_path / "migrations"
    directory.mkdir()
    for migration in setup.load_migrations():
        (directory / migration.name).write_bytes(migration.sql.encode("utf-8"))
    monkeypatch.setattr(setup, "files", lambda package: tmp_path)
    return directory


@async_test
async def test_fresh_database_and_restart_preserve_job_and_history(async_store_factory):
    async with async_store_factory(initialized=False) as store:
        assert (await prepare(store)) == {"phase": "ready", "version": VERSION, "applied": VERSION}
        project = (await store.create_project("신규 설치"))
        job = {"id": "j", "project_id": project["id"], "request": "보존할 입력"}
        (await store.save_job(job))
        async with store.transaction(mode="read") as conn:
            before = (await (await conn.execute("SELECT * FROM public.schema_migrations")).fetchall())
            assert (await (await conn.execute("SELECT to_regclass('core.installation') AS name")).fetchone())["name"] is None
        assert (await prepare(store))["applied"] == 0
        (await store.require_ready())
        assert (await store.jobs())[0]["request"] == job["request"]
        async with store.transaction(mode="read") as conn:
            assert (await (await conn.execute("SELECT * FROM public.schema_migrations")).fetchall()) == before


@async_test
async def test_next_migration_is_applied_once(async_store_factory, migration_files):
    async with async_store_factory(initialized=True) as store:
        (migration_files / NEXT).write_text("CREATE TABLE core.second_change(id integer);", encoding="utf-8")
        with pytest.raises(setup.MigrationError, match="미적용"):
            (await store.require_ready())
        assert (await prepare(store)) == {"phase": "ready", "version": VERSION + 1, "applied": 1}
        assert (await prepare(store))["applied"] == 0
        async with store.transaction(mode="read") as conn:
            assert [row["version"] for row in (await (await conn.execute("SELECT version FROM public.schema_migrations ORDER BY version")).fetchall())] == list(range(1, VERSION + 2))


@async_test
async def test_missing_app_table_rolls_back_before_checkpoint_setup(async_store_factory, migration_files, monkeypatch):
    async with async_store_factory(initialized=True) as store:
        (migration_files / NEXT).write_text("DROP TABLE workflow.workflow_task_results;", encoding="utf-8")
        checkpoint_setup = Mock(side_effect=AssertionError("앱 준비 실패 뒤 SDK를 실행하면 안 된다."))
        monkeypatch.setattr("backend.knowledge.core.checkpoint_store", checkpoint_setup)
        with pytest.raises(setup.MigrationError, match="필수 저장소 테이블"):
            (await prepare(store))
        checkpoint_setup.assert_not_called()
        async with store.transaction(mode="read") as conn:
            assert (await (await conn.execute("SELECT to_regclass('workflow.workflow_task_results') AS name")).fetchone())["name"]
            assert (await (await conn.execute("SELECT version FROM public.schema_migrations ORDER BY version")).fetchall()) == [{"version": n} for n in range(1, VERSION + 1)]


@pytest.mark.parametrize("already_installed", [False, True])
@async_test
async def test_failure_rolls_back_all_pending_sql_and_history(async_store_factory, migration_files, capsys, already_installed):
    async with async_store_factory(initialized=False) as store:
        if already_installed:
            (await prepare(store))
        (migration_files / NEXT).write_text("CREATE TABLE public.should_rollback(id integer); SELECT 'fake-sensitive-fixture'::integer;", encoding="utf-8")
        with pytest.raises(setup.MigrationError, match=NEXT) as caught:
            (await prepare(store))
        assert "fake-sensitive-fixture" not in str(caught.value)
        output = capsys.readouterr()
        assert "fake-sensitive-fixture" not in output.err + output.out
        assert f"migration={NEXT}" in output.err + output.out
        async with store.transaction(mode="read") as conn:
            for table in ("public.should_rollback",):
                assert (await (await conn.execute("SELECT to_regclass(%s) AS name", (table,))).fetchone())["name"] is None
            if already_installed:
                assert (await (await conn.execute("SELECT version FROM public.schema_migrations ORDER BY version")).fetchall()) == [{"version": n} for n in range(1, VERSION + 1)]
            else:
                for table in ("public.users", "public.schema_migrations", "core.jobs"):
                    assert (await (await conn.execute("SELECT to_regclass(%s) AS name", (table,))).fetchone())["name"] is None


@pytest.mark.parametrize("change", ["modified", "missing_middle", "missing_latest", "db_gap", "db_ahead"])
@async_test
async def test_invalid_history_stops_before_checkpoint_setup(async_store_factory, migration_files, monkeypatch, change):
    async with async_store_factory(initialized=True) as store:
        if change == "modified":
            path = migration_files / "001.sql"
            path.write_bytes(path.read_bytes() + b"\n-- changed\n")
        elif change == "missing_middle":
            (migration_files / "002.sql").unlink()
        elif change == "missing_latest":
            path = migration_files / NEXT
            path.write_text("SELECT 1;", encoding="utf-8")
            (await prepare(store))
            path.unlink()
        else:
            async with store.transaction() as conn:
                if change == "db_gap":
                    (await conn.execute("DELETE FROM public.schema_migrations WHERE version=1"))
                    (migration_files / NEXT).write_text("SELECT 1;", encoding="utf-8")
                else:
                    (await conn.execute("INSERT INTO public.schema_migrations(version,checksum) VALUES (%s,'test')", (VERSION + 1,)))
        checkpoint_setup = Mock(side_effect=AssertionError("이력 검사 전에 checkpoint를 변경하면 안 된다."))
        monkeypatch.setattr("backend.knowledge.core.checkpoint_store", checkpoint_setup)
        with pytest.raises(setup.MigrationError):
            (await prepare(store))
        checkpoint_setup.assert_not_called()


@pytest.mark.parametrize("filename", ["000.sql", "1.sql", NEXT])
def test_migration_files_must_start_at_001(migration_files, filename):
    (migration_files / "001.sql").rename(migration_files / filename)
    with pytest.raises(setup.MigrationError):
        setup.load_migrations()


@pytest.mark.parametrize("table", ["public.users", "core.jobs", "public.magi_jobs"])
@async_test
async def test_existing_tables_without_history_are_not_adopted(async_store_factory, table):
    async with async_store_factory(initialized=False) as store:
        async with store.transaction() as conn:
            (await conn.execute("CREATE SCHEMA IF NOT EXISTS core"))
            (await conn.execute(f"CREATE TABLE {table} (id text)"))
            (await conn.execute(f"INSERT INTO {table} VALUES ('preserved')"))
        with pytest.raises(setup.MigrationError, match="이력 없이"):
            (await prepare(store))
        async with store.transaction(mode="read") as conn:
            assert (await (await conn.execute(f"SELECT id FROM {table}")).fetchone())["id"] == "preserved"
            assert (await (await conn.execute("SELECT to_regclass('public.schema_migrations') AS name")).fetchone())["name"] is None


@async_test
async def test_checkpoint_failure_keeps_sql_history_and_retries(async_store_factory, monkeypatch):
    async with async_store_factory(initialized=False) as store:
        @asynccontextmanager
        async def failing_saver(store):
            yield SimpleNamespace(setup=AsyncMock(side_effect=RuntimeError("fake-private-driver-message")))

        with monkeypatch.context() as patch:
            patch.setattr("backend.knowledge.core.checkpoint_store", failing_saver)
            with pytest.raises(setup.MigrationError, match="checkpoints") as caught:
                (await prepare(store))
            assert "fake-private-driver-message" not in str(caught.value)
        async with store.transaction(mode="read") as conn:
            assert len((await (await conn.execute("SELECT version FROM public.schema_migrations")).fetchall())) == VERSION
        with pytest.raises(setup.MigrationError, match="필수 저장소 테이블"):
            (await store.require_ready())
        assert (await prepare(store))["applied"] == 0
        (await store.require_ready())


@async_test
async def test_missing_public_create_permission_rolls_back(async_store_factory):
    async with async_store_factory(initialized=False) as store:
        async with store.test_admin_transaction() as conn:
            (await conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC,ci_service"))
        with pytest.raises(setup.MigrationError):
            (await prepare(store))
        async with store.transaction(mode="read") as conn:
            assert (await (await conn.execute("SELECT to_regclass('public.schema_migrations') AS name")).fetchone())["name"] is None


@async_test
async def test_missing_database_create_permission_rolls_back(async_store_factory):
    async with async_store_factory(initialized=False) as store:
        async with store.test_admin_transaction() as conn:
            (await conn.execute("DO $$ BEGIN EXECUTE format('REVOKE CREATE ON DATABASE %I FROM PUBLIC,ci_service', current_database()); END $$"))
        with pytest.raises(setup.MigrationError):
            (await prepare(store))
        async with store.transaction(mode="read") as conn:
            for table in ("public.users", "public.schema_migrations"):
                assert (await (await conn.execute("SELECT to_regclass(%s) AS name", (table,))).fetchone())["name"] is None


@async_test
async def test_checkpoint_version_mismatch_is_not_ready(async_store_factory):
    async with async_store_factory(initialized=True) as store:
        async with store.transaction() as conn:
            (await conn.execute("INSERT INTO workflow.checkpoint_migrations(v) VALUES (999)"))
        with pytest.raises(setup.MigrationError, match="checkpoint 저장소 준비 버전"):
            (await store.require_ready())


@async_test
async def test_prepare_requires_process_lock(async_store_factory):
    async with async_store_factory(initialized=False) as store:
        with pytest.raises(setup.MigrationError, match="프로세스 잠금"):
            (await setup.migrate(store, runtime=SimpleNamespace(store=store, connection=None)))


@pytest.mark.parametrize("superuser,bypassrls,locked", [(True, False, False), (False, True, False), (False, False, True)])
@async_test
async def test_runtime_rejects_privileged_role_or_busy_process(superuser, bypassrls, locked, monkeypatch):
    conn = SimpleNamespace(execute=AsyncMock(), close=AsyncMock())
    cursor = SimpleNamespace(fetchone=AsyncMock())
    conn.execute.return_value = cursor
    cursor.fetchone.side_effect = [
        {"rolsuper": superuser, "rolbypassrls": bypassrls}, {"acquired": not locked},
    ]
    monkeypatch.setattr("psycopg.AsyncConnection.connect", AsyncMock(return_value=conn))
    store = KnowledgeStore(KnowledgeConfig({}))
    runtime = PublicRuntime(store)
    with pytest.raises(InvalidStateError):
        (await runtime.acquire(recover=False))
    assert runtime.connection is None
    conn.close.assert_awaited_once()


@async_test
async def test_real_process_lock_is_held_through_checkpoint_setup(async_store_factory, monkeypatch):
    async with async_store_factory(initialized=False) as store:
        if not (os.environ.get("CI") == "true" and os.environ.get("CI_POSTGRES") == "1"):
            pytest.skip("독립 DB 세션 잠금은 CI PostgreSQL에서 검증한다.")
        from backend.knowledge import core

        original = core.checkpoint_store

        @asynccontextmanager
        async def check_lock(store):
            competitor = PublicRuntime(store)
            with pytest.raises(InvalidStateError, match="다른 공개 백엔드"):
                (await competitor.acquire(recover=False))
            async with original(store) as saver:
                yield saver

        monkeypatch.setattr(core, "checkpoint_store", check_lock)
        (await prepare(store))
        next_runtime = PublicRuntime(store)
        try:
            (await next_runtime.acquire(recover=False))
        finally:
            (await next_runtime.close())
