"""기존 이력과 RLS를 보존하는 명시적 접두사 전환."""

from importlib.resources import files
import logging

from backend.knowledge.config import KnowledgeError


TABLES = ('schema_versions', 'projects', 'jobs', 'executions', 'snapshots', 'artifacts',
          'nodes', 'edges', 'models', 'embedding_queue', 'embeddings', 'chunk_sets',
          'chunks', 'chunk_vectors', 'deleted_jobs', 'cleanup_commits', 'deleted_nodes',
          'users', 'sessions', 'login_states', 'service_lease', 'daily_usage', 'cost_calls',
          'admissions', 'admin_audit', 'service_settings', 'request_windows')
PENDING = 'prefix-files-pending'
NOTICE = '이전 저장 형식입니다. python -m backend.knowledge.rename 명령으로 먼저 전환하세요.'
LOGGER = logging.getLogger('backend.knowledge.store')


def schema_state(conn):
    rows = conn.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname=current_schema() AND c.relkind IN ('r','p')").fetchall()
    names = {r['relname'] for r in rows}
    old = {'magi_' + name for name in TABLES} & names
    new = set(TABLES) & names
    if old and new:
        raise KnowledgeError('이전·새 DB 객체가 혼재합니다. 백업과 충돌 객체를 확인하세요.')
    if old:
        if old != {'magi_' + name for name in TABLES}:
            raise KnowledgeError('이전 DB 스키마가 완전하지 않습니다. 먼저 기존 버전의 마이그레이션을 완료하세요.')
        return 'legacy'
    if new:
        if new != set(TABLES):
            raise KnowledgeError('새 DB 스키마가 완전하지 않습니다.')
        return 'current'
    return 'empty'


def preflight(conn):
    """현재 스키마의 앱 소유 객체만 대상으로 충돌을 먼저 확인한다."""
    rows = conn.execute("SELECT c.oid,c.relname,c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname=current_schema()").fetchall()
    names = {r['relname'] for r in rows}
    owned = conn.execute("SELECT DISTINCT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=current_schema() AND (c.relname=ANY(%s) OR "
        "EXISTS(SELECT 1 FROM pg_index i JOIN pg_class t ON t.oid=i.indrelid WHERE i.indexrelid=c.oid AND t.relname=ANY(%s)) OR "
        "EXISTS(SELECT 1 FROM pg_depend d JOIN pg_class t ON t.oid=d.refobjid WHERE d.objid=c.oid AND c.relkind='S' AND t.relname=ANY(%s)))",
        (['magi_' + n for n in TABLES],) * 3).fetchall()
    if any(r['relname'].startswith('magi_') and r['relname'][5:] in names for r in owned):
        raise KnowledgeError('DB 객체의 새 이름이 이미 존재합니다.')
    constraints = conn.execute("SELECT c.conrelid,c.conname FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid "
        "JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname=current_schema() AND t.relname=ANY(%s)",
        (['magi_' + n for n in TABLES],)).fetchall()
    existing = {(r['conrelid'], r['conname']) for r in constraints}
    if any(r['conname'].startswith('magi_') and (r['conrelid'], r['conname'][5:]) in existing for r in constraints):
        raise KnowledgeError('DB 제약조건의 새 이름이 이미 존재합니다.')
    policies = conn.execute("SELECT tablename,policyname FROM pg_policies WHERE schemaname=current_schema()").fetchall()
    if any(r['tablename'] in {'magi_' + n for n in TABLES} and r['policyname'] == 'owner' for r in policies):
        raise KnowledgeError('DB 정책의 새 이름이 이미 존재합니다.')


def run_migrations(conn, state, *, pending_files=False, entering=None):
    entering = entering or (lambda stage, name=None: None)
    applied, skipped = 0, 0
    if state == 'legacy':
        preflight(conn)
        versions = {r['version'] for r in conn.execute('SELECT version FROM magi_schema_versions').fetchall()}
        if versions != {f'{i:03}.sql' for i in range(1, 9)}:
            raise KnowledgeError('이전 DB의 마이그레이션 이력이 예상과 다릅니다.')
    elif state == 'empty':
        conn.execute('CREATE TABLE magi_schema_versions (version text PRIMARY KEY)')
        versions = set()
    else:
        versions = {r['version'] for r in conn.execute('SELECT version FROM schema_versions').fetchall()}
        if '009.sql' not in versions:
            raise KnowledgeError('새 DB의 전환 이력이 누락되었습니다.')
        for version in sorted(v for v in versions if v.endswith('.sql')):
            entering('version_check', version)
            LOGGER.info('DB migration skipped migration=%s', version)
        return 0, len([v for v in versions if v.endswith('.sql')])
    # 구 정책은 역사적 SQL을 적용하는 이 트랜잭션에서만 사용한다.
    conn.execute("SELECT set_config('magi.internal','on',true),set_config('app.internal','on',true)")
    entering('list_files')
    root = files('backend.knowledge').joinpath('migrations')
    for i in range(1, 10):
        name = f'{i:03}.sql'
        entering('version_check', name)
        if name in versions:
            skipped += 1
            LOGGER.info('DB migration skipped migration=%s', name)
            continue
        entering('read_file', name)
        sql = root.joinpath(name).read_text(encoding='utf-8')
        entering('execute', name)
        conn.execute(sql)
        ledger = 'schema_versions' if i == 9 else 'magi_schema_versions'
        entering('record_version', name)
        conn.execute(f'INSERT INTO {ledger} VALUES (%s)', (name,))
        applied += 1
        LOGGER.info('DB migration executed migration=%s commit=pending', name)
    if pending_files:
        conn.execute('INSERT INTO schema_versions VALUES (%s)', (PENDING,))
    return applied, skipped


def migrate(store):
    stage, migration_name = 'transaction_setup', None
    applied, skipped = 0, 0

    def entering(name, migration=None):
        nonlocal stage, migration_name
        stage, migration_name = name, migration
        LOGGER.info('DB migration stage=%s migration=%s', stage, migration_name)

    try:
        entering('transaction_setup')
        with store.transaction(mode='maintenance') as conn:
            entering('vector_check')
            if not conn.execute("SELECT 1 FROM pg_extension WHERE extname='vector'").fetchone():
                raise KnowledgeError('전용 DB에 vector 확장을 먼저 활성화하세요.')
            entering('migration_lock')
            conn.execute('SELECT pg_advisory_xact_lock(72410631)')
            entering('version_table')
            state = schema_state(conn)
            if state == 'legacy':
                raise KnowledgeError(NOTICE)
            if state == 'current':
                versions = {r['version'] for r in conn.execute('SELECT version FROM schema_versions').fetchall()}
                if any(v.startswith(PENDING) for v in versions):
                    raise KnowledgeError('파일 전환이 완료되지 않았습니다. 전환 명령을 재실행하세요.')
            applied, skipped = run_migrations(conn, state, entering=entering)
            entering('transaction_exit')
    except Exception as exc:
        cause = exc.__cause__ or exc.__context__
        LOGGER.error('DB migration failed stage=%s migration=%s exception_type=%s cause_type=%s',
                     stage, migration_name, type(exc).__name__, type(cause).__name__ if cause is not None else None)
        raise
    LOGGER.info('DB migration completed applied=%s skipped=%s', applied, skipped)
