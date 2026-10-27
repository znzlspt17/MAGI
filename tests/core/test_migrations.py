"""번호별 SQL 적용·롤백·불변 이력과 checkpoint 준비 재시도를 검증한다."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.access.runtime import PublicRuntime
from backend.errors import InvalidStateError
from backend.knowledge import setup
from backend.knowledge.config import KnowledgeConfig
from backend.knowledge.store import KnowledgeStore


def prepare(store):
    runtime = PublicRuntime(store)
    try:
        runtime.acquire(recover=False)
        return setup.migrate(store, runtime=runtime)
    finally:
        runtime.close()


@pytest.fixture
def migration_files(tmp_path, monkeypatch):
    directory = tmp_path / "migrations"
    directory.mkdir()
    for migration in setup.load_migrations():
        (directory / migration.name).write_bytes(migration.sql.encode("utf-8"))
    monkeypatch.setattr(setup, "files", lambda package: tmp_path)
    return directory


def test_fresh_database_and_restart_preserve_job_and_history(empty_store):
    assert prepare(empty_store) == {"phase": "ready", "version": 2, "applied": 2}
    project = empty_store.create_project("신규 설치")
    job = {"id": "j", "project_id": project["id"], "request": "보존할 입력"}
    empty_store.save_job(job)
    with empty_store.transaction(mode="read") as conn:
        before = conn.execute("SELECT * FROM public.schema_migrations").fetchall()
        assert conn.execute("SELECT to_regclass('core.installation') AS name").fetchone()["name"] is None
    assert prepare(empty_store)["applied"] == 0
    empty_store.require_ready()
    assert empty_store.jobs()[0]["request"] == job["request"]
    with empty_store.transaction(mode="read") as conn:
        assert conn.execute("SELECT * FROM public.schema_migrations").fetchall() == before


def test_next_migration_is_applied_once(store, migration_files):
    (migration_files / "003.sql").write_text("CREATE TABLE core.second_change(id integer);", encoding="utf-8")
    with pytest.raises(setup.MigrationError, match="미적용"):
        store.require_ready()
    assert prepare(store) == {"phase": "ready", "version": 3, "applied": 1}
    assert prepare(store)["applied"] == 0
    with store.transaction(mode="read") as conn:
        assert [row["version"] for row in conn.execute("SELECT version FROM public.schema_migrations ORDER BY version").fetchall()] == [1, 2, 3]


def test_missing_app_table_rolls_back_before_checkpoint_setup(store, migration_files, monkeypatch):
    (migration_files / "003.sql").write_text("DROP TABLE workflow.workflow_task_results;", encoding="utf-8")
    checkpoint_setup = Mock(side_effect=AssertionError("앱 준비 실패 뒤 SDK를 실행하면 안 된다."))
    monkeypatch.setattr("backend.knowledge.core.checkpoint_store", checkpoint_setup)
    with pytest.raises(setup.MigrationError, match="필수 저장소 테이블"):
        prepare(store)
    checkpoint_setup.assert_not_called()
    with store.transaction(mode="read") as conn:
        assert conn.execute("SELECT to_regclass('workflow.workflow_task_results') AS name").fetchone()["name"]
        assert conn.execute("SELECT version FROM public.schema_migrations").fetchall() == [{"version": 1}, {"version": 2}]


@pytest.mark.parametrize("already_installed", [False, True])
def test_failure_rolls_back_all_pending_sql_and_history(empty_store, migration_files, capsys, already_installed):
    if already_installed:
        prepare(empty_store)
    (migration_files / "003.sql").write_text("CREATE TABLE public.should_rollback(id integer); SELECT 'fake-sensitive-fixture'::integer;", encoding="utf-8")
    with pytest.raises(setup.MigrationError, match="003.sql") as caught:
        prepare(empty_store)
    assert "fake-sensitive-fixture" not in str(caught.value)
    output = capsys.readouterr()
    assert "fake-sensitive-fixture" not in output.err + output.out
    assert "migration=003.sql" in output.err + output.out
    with empty_store.transaction(mode="read") as conn:
        for table in ("public.should_rollback",):
            assert conn.execute("SELECT to_regclass(%s) AS name", (table,)).fetchone()["name"] is None
        if already_installed:
            assert conn.execute("SELECT version FROM public.schema_migrations").fetchall() == [{"version": 1}, {"version": 2}]
        else:
            for table in ("public.users", "public.schema_migrations", "core.jobs"):
                assert conn.execute("SELECT to_regclass(%s) AS name", (table,)).fetchone()["name"] is None


@pytest.mark.parametrize("change", ["modified", "missing_middle", "missing_latest", "db_gap", "db_ahead"])
def test_invalid_history_stops_before_checkpoint_setup(store, migration_files, monkeypatch, change):
    if change == "modified":
        path = migration_files / "001.sql"
        path.write_bytes(path.read_bytes() + b"\n-- changed\n")
    elif change == "missing_middle":
        (migration_files / "004.sql").write_text("SELECT 1;", encoding="utf-8")
    elif change == "missing_latest":
        path = migration_files / "003.sql"
        path.write_text("SELECT 1;", encoding="utf-8")
        prepare(store)
        path.unlink()
    else:
        with store.transaction() as conn:
            if change == "db_gap":
                conn.execute("DELETE FROM public.schema_migrations WHERE version=1")
                (migration_files / "003.sql").write_text("SELECT 1;", encoding="utf-8")
            else:
                conn.execute("INSERT INTO public.schema_migrations(version,checksum) VALUES (3,'test')")
    checkpoint_setup = Mock(side_effect=AssertionError("이력 검사 전에 checkpoint를 변경하면 안 된다."))
    monkeypatch.setattr("backend.knowledge.core.checkpoint_store", checkpoint_setup)
    with pytest.raises(setup.MigrationError):
        prepare(store)
    checkpoint_setup.assert_not_called()


@pytest.mark.parametrize("filename", ["000.sql", "1.sql", "005.sql"])
def test_migration_files_must_start_at_001(migration_files, filename):
    (migration_files / "001.sql").rename(migration_files / filename)
    with pytest.raises(setup.MigrationError):
        setup.load_migrations()


@pytest.mark.parametrize("table", ["public.users", "core.jobs", "public.magi_jobs"])
def test_existing_tables_without_history_are_not_adopted(empty_store, table):
    with empty_store.transaction() as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS core")
        conn.execute(f"CREATE TABLE {table} (id text)")
        conn.execute(f"INSERT INTO {table} VALUES ('preserved')")
    with pytest.raises(setup.MigrationError, match="이력 없이"):
        prepare(empty_store)
    with empty_store.transaction(mode="read") as conn:
        assert conn.execute(f"SELECT id FROM {table}").fetchone()["id"] == "preserved"
        assert conn.execute("SELECT to_regclass('public.schema_migrations') AS name").fetchone()["name"] is None


def test_checkpoint_failure_keeps_sql_history_and_retries(empty_store, monkeypatch):
    @contextmanager
    def failing_saver(store):
        yield SimpleNamespace(setup=Mock(side_effect=RuntimeError("fake-private-driver-message")))

    with monkeypatch.context() as patch:
        patch.setattr("backend.knowledge.core.checkpoint_store", failing_saver)
        with pytest.raises(setup.MigrationError, match="checkpoints") as caught:
            prepare(empty_store)
        assert "fake-private-driver-message" not in str(caught.value)
    with empty_store.transaction(mode="read") as conn:
        assert len(conn.execute("SELECT version FROM public.schema_migrations").fetchall()) == 2
    with pytest.raises(setup.MigrationError, match="필수 저장소 테이블"):
        empty_store.require_ready()
    assert prepare(empty_store)["applied"] == 0
    empty_store.require_ready()


def test_missing_public_create_permission_rolls_back(empty_store, admin_transaction):
    with admin_transaction() as conn:
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC,ci_service")
    with pytest.raises(setup.MigrationError):
        prepare(empty_store)
    with empty_store.transaction(mode="read") as conn:
        assert conn.execute("SELECT to_regclass('public.schema_migrations') AS name").fetchone()["name"] is None


def test_missing_database_create_permission_rolls_back(empty_store, admin_transaction):
    with admin_transaction() as conn:
        conn.execute("DO $$ BEGIN EXECUTE format('REVOKE CREATE ON DATABASE %I FROM PUBLIC,ci_service', current_database()); END $$")
    with pytest.raises(setup.MigrationError):
        prepare(empty_store)
    with empty_store.transaction(mode="read") as conn:
        for table in ("public.users", "public.schema_migrations"):
            assert conn.execute("SELECT to_regclass(%s) AS name", (table,)).fetchone()["name"] is None


def test_checkpoint_version_mismatch_is_not_ready(store):
    with store.transaction() as conn:
        conn.execute("INSERT INTO workflow.checkpoint_migrations(v) VALUES (999)")
    with pytest.raises(setup.MigrationError, match="checkpoint 저장소 준비 버전"):
        store.require_ready()


def test_prepare_requires_process_lock(empty_store):
    with pytest.raises(setup.MigrationError, match="프로세스 잠금"):
        setup.migrate(empty_store, runtime=SimpleNamespace(store=empty_store, connection=None))


@pytest.mark.parametrize("superuser,bypassrls,locked", [(True, False, False), (False, True, False), (False, False, True)])
def test_runtime_rejects_privileged_role_or_busy_process(superuser, bypassrls, locked):
    conn = Mock()
    conn.execute.return_value.fetchone.side_effect = [
        {"rolsuper": superuser, "rolbypassrls": bypassrls}, {"acquired": not locked},
    ]
    store = KnowledgeStore(KnowledgeConfig({}), connect=lambda **kwargs: conn)
    runtime = PublicRuntime(store)
    with pytest.raises(InvalidStateError):
        runtime.acquire(recover=False)
    assert runtime.connection is None
    conn.close.assert_called_once()


def test_real_process_lock_is_held_through_checkpoint_setup(empty_store, monkeypatch):
    if not empty_store.config.connection:
        pytest.skip("독립 DB 세션 잠금은 CI PostgreSQL에서 검증한다.")
    from backend.knowledge import core

    original = core.checkpoint_store

    @contextmanager
    def check_lock(store):
        competitor = PublicRuntime(store)
        with pytest.raises(InvalidStateError, match="다른 공개 백엔드"):
            competitor.acquire(recover=False)
        with original(store) as saver:
            yield saver

    monkeypatch.setattr(core, "checkpoint_store", check_lock)
    prepare(empty_store)
    next_runtime = PublicRuntime(empty_store)
    try:
        next_runtime.acquire(recover=False)
    finally:
        next_runtime.close()
