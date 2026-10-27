"""프로세스 잠금 아래 번호별 SQL과 공식 checkpoint 저장소를 준비한다."""

from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
from protocol.logging import get_logger
import re

from backend.knowledge.config import KnowledgeError


logger = get_logger(__name__)
ACCOUNT_TABLES = (
    "users", "sessions", "login_states", "execution_leases", "daily_usage",
    "cost_calls", "admissions", "admin_audit", "service_settings", "request_windows",
)
CORE_TABLES = (
    "projects", "jobs", "executions", "document_bodies", "document_versions",
    "execution_events", "model_usage", "projection_commits", "nodes", "edges",
    "models", "embedding_queue", "chunks", "chunk_sets", "chunk_vectors",
    "project_decisions", "deleted_jobs", "deleted_nodes", "cleanup_commits",
)
WORKFLOW_TABLES = (
    "checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations",
    "workflow_task_results",
)


class MigrationError(KnowledgeError):
    """SQL·접속 오류 원문을 포함하지 않는 고정 진단 메시지."""

    def __init__(self, message, *, migration="-"):
        self.migration = migration if re.fullmatch(r"[0-9]{3}[.]sql", migration) else "-"
        super().__init__(message)


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    checksum: str
    sql: str


def load_migrations():
    result = []
    for entry in files("backend.knowledge").joinpath("migrations").iterdir():
        if not entry.name.endswith(".sql"):
            continue
        match = re.fullmatch(r"([0-9]{3})[.]sql", entry.name)
        if not match or not entry.is_file():
            raise MigrationError("마이그레이션 파일 이름은 001.sql부터 세 자리 번호를 사용해야 합니다.")
        try:
            content = entry.read_bytes()
            sql = content.decode("utf-8")
        except (OSError, UnicodeError):
            raise MigrationError("마이그레이션 SQL 파일을 읽지 못했습니다.", migration=entry.name) from None
        result.append(Migration(int(match[1]), entry.name, sha256(content).hexdigest(), sql))
    result.sort(key=lambda item: item.version)
    if not result or [item.version for item in result] != list(range(1, len(result) + 1)):
        raise MigrationError("마이그레이션 파일 번호가 001부터 연속되지 않습니다.")
    return result


def _history(conn):
    if not conn.execute("SELECT to_regclass('public.schema_migrations') AS name").fetchone()["name"]:
        return []
    return conn.execute("SELECT version,checksum FROM public.schema_migrations ORDER BY version").fetchall()


def _validate_history(applied, migrations):
    versions = [row["version"] for row in applied]
    if versions and versions[-1] > len(migrations):
        raise MigrationError("DB 마이그레이션 버전이 현재 코드보다 높습니다. 적용 파일 삭제 또는 이전 이미지 실행 여부를 확인하세요.")
    if versions != list(range(1, len(applied) + 1)):
        raise MigrationError("DB 마이그레이션 적용 이력이 연속되지 않습니다.")
    for row, migration in zip(applied, migrations):
        if row["checksum"] != migration.checksum:
            raise MigrationError("이미 적용한 마이그레이션 파일의 해시가 변경되었습니다.", migration=migration.name)


def _require_empty(conn):
    # 이력이 없는 기존 객체를 새 기준선으로 간주하거나 덮어쓰지 않는다.
    if conn.execute(
        "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE c.relkind IN ('r','p','v','m','f') AND n.nspname IN ('public','core','workflow') "
        "AND NOT (n.nspname='public' AND c.relname='schema_migrations') "
        "AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid='pg_class'::regclass "
        "AND d.objid=c.oid AND d.deptype='e') LIMIT 1",
    ).fetchone():
        raise MigrationError("마이그레이션 이력 없이 기존 테이블이 존재합니다. 빈 DB에서 시작하세요.")


def _require_app_tables(conn):
    for schema, tables in (("public", ACCOUNT_TABLES), ("core", CORE_TABLES), ("workflow", ("workflow_task_results",))):
        for table in tables:
            if not conn.execute("SELECT to_regclass(%s) AS name", (schema + "." + table,)).fetchone()["name"]:
                raise MigrationError("필수 저장소 테이블이 없습니다. DB 준비를 완료하세요.")


def _require_tables(conn):
    _require_app_tables(conn)
    for table in WORKFLOW_TABLES:
        if not conn.execute("SELECT to_regclass(%s) AS name", ("workflow." + table,)).fetchone()["name"]:
            raise MigrationError("필수 저장소 테이블이 없습니다. DB 준비를 완료하세요.")
    from langgraph.checkpoint.postgres import PostgresSaver

    row = conn.execute("SELECT max(v) AS version FROM workflow.checkpoint_migrations").fetchone()
    if row["version"] != len(PostgresSaver.MIGRATIONS) - 1:
        raise MigrationError("공식 checkpoint 저장소 준비 버전이 현재 코드와 다릅니다.")


def migrate(store, *, runtime):
    """호출자는 연결을 열어 프로세스 잠금을 얻고 준비 종료까지 유지해야 한다."""
    if runtime.store is not store or runtime.connection is None:
        raise MigrationError("DB 준비 전에 백엔드 프로세스 잠금이 필요합니다.")
    stage, filename = "files", "-"
    try:
        migrations = load_migrations()
        stage = "sql"
        with store.transaction(mode="maintenance") as conn:
            conn.execute("SET LOCAL statement_timeout=0")
            conn.execute("SET LOCAL search_path TO public")
            applied = _history(conn)
            _validate_history(applied, migrations)
            if not applied:
                _require_empty(conn)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS public.schema_migrations ("
                "version integer PRIMARY KEY CHECK(version>0),checksum text NOT NULL,"
                "applied_at timestamptz NOT NULL DEFAULT now())"
            )
            for migration in migrations[len(applied):]:
                filename = migration.name
                conn.execute("SET LOCAL search_path TO public")
                conn.execute(migration.sql)
                conn.execute(
                    "INSERT INTO public.schema_migrations(version,checksum) VALUES (%s,%s)",
                    (migration.version, migration.checksum),
                )
            # workflow 스키마가 없을 때 SDK가 public에 테이블을 만드는 것을 차단한다.
            _require_app_tables(conn)
        stage, filename = "checkpoints", "-"
        from backend.knowledge.core import checkpoint_store

        with checkpoint_store(store) as saver:
            saver.setup()
        stage = "ready"
        require_ready(store)
        return {"phase": "ready", "version": migrations[-1].version, "applied": len(migrations) - len(applied)}
    except Exception as exc:
        # 예외 원문 대신 단계·검증된 파일명·유형만 기록한다.
        if isinstance(exc, MigrationError) and exc.migration != "-":
            filename = exc.migration
        original = exc.__context__ if isinstance(exc, KnowledgeError) and exc.__context__ else exc
        logger.error("DB preparation failed stage=%s migration=%s exception_type=%s", stage, filename, type(original).__name__)
        if isinstance(exc, MigrationError):
            raise
        raise MigrationError("DB 준비에 실패했습니다. 단계: " + stage + " 파일: " + filename + " 오류 유형: " + type(original).__name__) from None


def require_ready(store):
    migrations = load_migrations()
    with store.transaction(mode="read") as conn:
        applied = _history(conn)
        _validate_history(applied, migrations)
        if len(applied) != len(migrations):
            raise MigrationError("미적용 DB 마이그레이션이 있습니다. backend를 시작해 자동 마이그레이션을 완료하세요.")
        _require_tables(conn)
