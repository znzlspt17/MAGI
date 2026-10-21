"""중지된 설치의 접두사 전환. 보호 설정 파일을 읽지 않으며 기본은 검사다."""

import argparse
from contextlib import contextmanager, ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from backend.knowledge.config import KnowledgeConfig, KnowledgeError
from backend.knowledge.projection import digest
from backend.knowledge.schema import PENDING, preflight, run_migrations, schema_state
from backend.knowledge.format_guard import PENDING_FILE


OLD_STATE = 'state/magi_state.json'
NEW_STATE = 'state/state.json'
PATH_FIELDS = {'output_dir', 'state_path', 'approval_candidate_path', 'final_spec_path',
               'critical_report_path', 'heartbeat_path', 'questions_path', 'evidence_registry_path',
               'project_manifest_path', 'web_sources_path', 'approval_candidate_spec',
               'final_agent_spec', 'critical_report'}
CONTAINERS = {'state', 'result', 'detail', 'nodes', 'latest_completed', 'executions', 'jobs'}
PHASES = {'planned', 'staged', 'database', 'files', 'published', 'complete'}


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_path(path):
    path = Path(os.path.abspath(path))
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in (path, *path.parents)):
        raise KnowledgeError('심볼릭 링크·junction 경로는 전환할 수 없습니다.')
    return path


def root_pairs(data_dir, output_dir):
    result = []
    for source, old_name, new_name in ((data_dir, 'magi_web_data', 'web_data'),
                                      (output_dir, 'magi_output', 'output')):
        if source is not None:
            old = safe_path(source)
            new = old.with_name(new_name) if old.name == old_name else old
            result.append((old, safe_path(new)))
    if any(a == b or a.is_relative_to(b) or b.is_relative_to(a)
           for i, (a, _) in enumerate(result) for b, _ in result[i + 1:]):
        raise KnowledgeError('작업 루트가 중복되거나 겹칩니다.')
    return result


def relocated(path, plan):
    path = safe_path(path)
    for old, new in plan['roots']:
        old, new = safe_path(old), safe_path(new)
        if old != new and not old.exists() and new.is_dir() and path.is_relative_to(old):
            return safe_path(new / path.relative_to(old))
    return path


def marker_paths(plan):
    roots = [relocated(a, plan) for a, _ in plan['roots']]
    if plan.get('model_dir'):
        roots.append(relocated(plan['model_dir'], plan))
    return [safe_path(root / PENDING_FILE) for root in roots]


def validate_plan(plan, data_dir, output_dir, model_dir, database):
    """진행 기록으로 임의 파일을 읽거나 덮어쓰지 못하게 경로를 재구성한다."""
    pairs = [[str(a), str(b)] for a, b in root_pairs(data_dir, output_dir)]
    model = str(safe_path(model_dir)) if model_dir is not None else None
    if (plan.get('version') != 1 or plan.get('roots') != pairs
            or plan.get('database') is not database or plan.get('model_dir') != model
            or plan.get('phase') not in PHASES
            or not re.fullmatch(r'[0-9a-f]{32}', str(plan.get('token', '')))):
        raise KnowledgeError('진행 기록과 명시한 전환 대상이 일치하지 않습니다.')
    expected = [{'source': a, 'target': b} for a, b in pairs if a != b]
    if plan.get('renames') != expected or not isinstance(plan.get('files'), list):
        raise KnowledgeError('진행 기록의 폴더 전환이 올바르지 않습니다.')
    sources, targets = set(), set()
    for row in plan['files']:
        if not isinstance(row, dict) or set(row) != {'source', 'target', 'stage', 'before', 'after'}:
            raise KnowledgeError('진행 기록의 파일 항목이 올바르지 않습니다.')
        source = safe_path(row['source'])
        target = None
        for a, _ in pairs:
            root = Path(a)
            if not source.is_relative_to(root):
                continue
            parts = source.relative_to(root).parts
            if len(parts) >= 2 and re.fullmatch(r'[0-9a-f]{32}', parts[0]):
                parts = parts[1:]
            relative = '/'.join(parts)
            if relative in {OLD_STATE, NEW_STATE, 'job.json', 'state/execution_history.json'}:
                target = source.with_name('state.json') if relative == OLD_STATE else source
        if model and source == Path(model) / 'magi_model_revision.json':
            target = Path(model) / 'model_revision.json'
        if (target is None or str(source) != row['source'] or str(target) != row['target']
                or str(source.with_name(source.name + '.prefix-stage')) != row['stage']
                or not all(re.fullmatch(r'[0-9a-f]{64}', str(row[k])) for k in ('before', 'after'))
                or str(source) in sources or str(target) in targets):
            raise KnowledgeError('진행 기록에 허용하지 않은 경로나 중복 대상이 있습니다.')
        sources.add(str(source)); targets.add(str(target))


def database_identity(conn):
    row = conn.execute("SELECT current_database() AS database,current_schema() AS schema,"
        "(SELECT oid::text FROM pg_namespace WHERE nspname=current_schema()) AS schema_oid,"
        "coalesce(to_regclass('schema_versions'),to_regclass('magi_schema_versions'))::oid::text AS ledger_oid,"
        "inet_server_addr()::text AS server_address,inet_server_port() AS server_port").fetchone()
    return digest(row)


def replace_path(value, roots):
    if not isinstance(value, str):
        return value
    normalize = str.casefold if os.name == 'nt' else (lambda item: item)
    if normalize(value.replace('\\', '/')) == normalize(OLD_STATE):
        return NEW_STATE
    result = value
    for old, new in roots:
        for separator in ('/', '\\'):
            a, b = str(old).replace('\\', separator), str(new).replace('\\', separator)
            if normalize(result) == normalize(a) or normalize(result).startswith(normalize(a + separator)):
                result = b + result[len(a):]
                break
    for separator in ('/', '\\'):
        suffix = separator + OLD_STATE.replace('/', separator)
        if normalize(result).endswith(normalize(suffix)):
            result = result[:-len(suffix)] + separator + NEW_STATE.replace('/', separator)
    return result


def transform(value, roots=()):
    """알려진 앱 경로 필드만 변환하고 원문·ID·임의 dict는 건드리지 않는다."""
    if isinstance(value, list):
        return [transform(item, roots) for item in value]
    if not isinstance(value, dict):
        return value
    result = dict(value)
    for key, item in value.items():
        if key in PATH_FIELDS:
            result[key] = replace_path(item, roots)
        elif key == 'created_artifacts' and isinstance(item, list):
            result[key] = [replace_path(p, roots) for p in item]
        elif key in CONTAINERS:
            result[key] = transform(item, roots)
    return result


def file_plan(data_dir=None, output_dir=None, model_dir=None):
    roots, renames, files = [], [], []
    for source, old_name, new_name in ((data_dir, 'magi_web_data', 'web_data'),
                                      (output_dir, 'magi_output', 'output')):
        if source is None:
            continue
        old = safe_path(source)
        if not old.is_dir():
            raise KnowledgeError('지정한 작업 폴더가 없습니다.')
        new = safe_path(old.with_name(new_name)) if old.name == old_name else old
        if new != old:
            if new.exists():
                raise KnowledgeError('대상 작업 폴더가 이미 존재합니다.')
            renames.append({'source': str(old), 'target': str(new)})
        roots.append((old, new))
    if any(a == b or a.is_relative_to(b) or b.is_relative_to(a)
           for i, (a, _) in enumerate(roots) for b, _ in roots[i + 1:]):
        raise KnowledgeError('작업 루트가 중복되거나 겹칩니다.')
    for root, destination in roots:
        jobs = [root]
        jobs += [safe_path(p) for p in root.iterdir() if p.is_dir() and re.fullmatch(r'[0-9a-f]{32}', p.name)]
        for job in jobs:
            for relative in (OLD_STATE, NEW_STATE, 'job.json', 'state/execution_history.json'):
                source = safe_path(job / relative)
                if not source.is_file():
                    continue
                target = source.with_name('state.json') if relative == OLD_STATE else source
                if target != source and target.exists():
                    raise KnowledgeError('이전·새 체크포인트가 동시에 존재합니다.')
                value = json.loads(source.read_text(encoding='utf-8'))
                content = json.dumps(transform(value, roots), ensure_ascii=False, indent=2) + '\n'
                if target == source and transform(value, roots) == value:
                    continue
                staged = source.with_name(source.name + '.prefix-stage')
                if staged.exists():
                    raise KnowledgeError('진행 기록 없는 전환 임시 파일이 있습니다.')
                files.append({'source': str(source), 'target': str(target), 'stage': str(staged),
                              'before': checksum(source), 'after': hashlib.sha256(content.encode()).hexdigest(),
                              'content': content})
    if model_dir is not None:
        root = safe_path(model_dir)
        old, new = safe_path(root / 'magi_model_revision.json'), safe_path(root / 'model_revision.json')
        if old.exists() and new.exists():
            raise KnowledgeError('이전·새 모델 revision 파일이 동시에 존재합니다.')
        if old.is_file():
            with old.open('r', encoding='utf-8', newline='') as stream:
                content = stream.read()
            stage = old.with_name(old.name + '.prefix-stage')
            if stage.exists():
                raise KnowledgeError('진행 기록 없는 모델 전환 임시 파일이 있습니다.')
            files.append({'source': str(old), 'target': str(new), 'stage': str(stage),
                          'before': checksum(old), 'after': checksum(old), 'content': content})
        elif not new.is_file():
            raise KnowledgeError('모델 revision 파일이 없습니다.')
    targets = [f['target'] for f in files]
    if len(set(targets)) != len(targets):
        raise KnowledgeError('전환 대상 경로가 중복됩니다.')
    return {'version': 1, 'phase': 'planned', 'roots': [[str(a), str(b)] for a, b in roots],
            'renames': renames, 'files': files}


def write_journal(path, plan):
    # 사용자 내용과 접속 설정을 진행 기록에 저장하지 않는다.
    payload = {**plan, 'files': [{k: v for k, v in row.items() if k != 'content'} for row in plan['files']]}
    temporary = safe_path(path.with_name(path.name + '.' + uuid4().hex + '.tmp'))
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@contextmanager
def process_locks():
    """구·신 임베딩 프로세스를 모두 배제한다. 잠금을 강제로 해제하지 않는다."""
    streams = []
    try:
        for name in ('magi-local-embedding.lock', 'local-embedding.lock'):
            path = safe_path(Path(tempfile.gettempdir()) / name)
            stream = path.open('a+b')
            streams.append(stream)
            if os.name == 'nt':
                import msvcrt
                stream.seek(0)
                if not stream.read(1):
                    stream.write(b'0'); stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, KnowledgeError):
        for stream in reversed(streams):
            stream.close()
        raise KnowledgeError('임베딩 프로세스를 먼저 종료하세요.') from None
    try:
        yield
    finally:
        for stream in reversed(streams):
            stream.close()


def artifact_updates(conn, roots, *, legacy=False):
    table = 'magi_artifacts' if legacy else 'artifacts'
    rows = conn.execute(f'SELECT id,snapshot_id,path,content FROM {table} WHERE path=ANY(%s)',
                        ([OLD_STATE, NEW_STATE, 'state/execution_history.json'],)).fetchall()
    inventory = conn.execute(f'SELECT id,snapshot_id,path FROM {table}').fetchall()
    targets = {row['id'] for row in inventory}
    paths = {(row['snapshot_id'], row['path']): row['id'] for row in inventory}
    updates = []
    for row in rows:
        path = NEW_STATE if row['path'] == OLD_STATE else row['path']
        ident = digest([row['snapshot_id'], path])
        if ((ident != row['id'] and ident in targets)
                or paths.get((row['snapshot_id'], path), row['id']) != row['id']):
            raise KnowledgeError('DB 체크포인트 대상이 이미 존재합니다.')
        content = json.dumps(transform(json.loads(row['content']), roots), ensure_ascii=False)
        updates.append((ident, path, content, digest(content), row['id']))
    return updates


def database_preflight(conn, roots):
    state = schema_state(conn)
    if state == 'empty':
        raise KnowledgeError('기존 DB가 없습니다. 신규 DB는 서비스에서 초기화하세요.')
    legacy = state == 'legacy'
    if legacy:
        preflight(conn)
        versions = {r['version'] for r in conn.execute('SELECT version FROM magi_schema_versions').fetchall()}
        if versions != {f'{i:03}.sql' for i in range(1, 9)}:
            raise KnowledgeError('이전 DB의 마이그레이션 이력이 예상과 다릅니다.')
        conn.execute("SELECT set_config('magi.internal','on',true)")
    else:
        versions = {r['version'] for r in conn.execute('SELECT version FROM schema_versions').fetchall()}
        if '009.sql' not in versions:
            raise KnowledgeError('새 DB의 전환 이력이 누락되었습니다.')
    artifact_updates(conn, roots, legacy=legacy)
    # JSON 파싱과 변환도 쓰기 전에 끝내어 잘못된 체크포인트를 거절한다.
    for table, column in (('jobs', 'data'), ('executions', 'data'), ('snapshots', 'state')):
        name = 'magi_' + table if legacy else table
        for row in conn.execute(f'SELECT {column} AS payload FROM {name}').fetchall():
            transform(row['payload'], roots)
    return state, versions, database_identity(conn)


def convert_database(conn, roots):
    from psycopg.types.json import Jsonb
    for table, column in (('jobs', 'data'), ('executions', 'data'), ('snapshots', 'state')):
        for row in conn.execute(f'SELECT id,{column} AS payload FROM {table}').fetchall():
            changed = transform(row['payload'], roots)
            if changed != row['payload']:
                conn.execute(f'UPDATE {table} SET {column}=%s WHERE id=%s', (Jsonb(changed), row['id']))
    updates = artifact_updates(conn, roots)
    for update in updates:
        conn.execute('UPDATE artifacts SET id=%s,path=%s,content=%s,content_hash=%s WHERE id=%s', update)


def publish(plan, journal):
    for row in plan['files']:
        source, target, stage = (relocated(row[k], plan) for k in ('source', 'target', 'stage'))
        if not stage.exists() and target.is_file() and checksum(target) == row['after']:
            if source != target and source.exists():
                if checksum(source) != row['before']:
                    raise KnowledgeError('전환 중 원본이 변경되었습니다.')
                # target 게시 직후 중단된 경우 원본 삭제만 마저 수행한다.
                source.unlink()
            continue
        if not stage.is_file() or checksum(stage) != row['after']:
            raise KnowledgeError('전환 임시 파일이 없거나 변경되었습니다. 백업으로 복구하세요.')
        if not source.is_file() or checksum(source) != row['before']:
            raise KnowledgeError('전환 중 원본이 변경되었습니다.')
        if source != target and target.exists():
            raise KnowledgeError('전환 대상 파일이 이미 존재합니다.')
        os.replace(stage, target)
        if source != target:
            source.unlink()
    plan['phase'] = 'files'
    write_journal(journal, plan)
    for row in plan['renames']:
        source, target = safe_path(row['source']), safe_path(row['target'])
        if source.exists() and target.exists():
            raise KnowledgeError('전환 대상 폴더가 이미 존재합니다.')
        if source.exists():
            source.rename(target)
        elif not target.is_dir():
            raise KnowledgeError('전환 대상 폴더를 찾을 수 없습니다.')
    plan['phase'] = 'published'
    write_journal(journal, plan)


def validate_published(plan):
    for row in plan['files']:
        source, target, stage = (relocated(row[k], plan) for k in ('source', 'target', 'stage'))
        if (not target.is_file() or checksum(target) != row['after'] or stage.exists()
                or (source != target and source.exists())):
            raise KnowledgeError('완료된 전환 파일이 없거나 변경되었습니다. 백업을 확인하세요.')
    for row in plan['renames']:
        if safe_path(row['source']).exists() or not safe_path(row['target']).is_dir():
            raise KnowledgeError('완료된 전환 폴더가 올바르지 않습니다.')


def transition(*, data_dir=None, output_dir=None, model_dir=None, store=None,
               apply=False, journal=None, backup_confirmed=False):
    journal = safe_path(journal or Path.cwd() / 'prefix-transition.json')
    if (journal.suffix != '.json' or journal.name == '.env' or journal.name.startswith('.env.')
            or journal.name in {'credentials.json', 'secrets.json', 'token.json'}
            or journal.name.startswith(('service-account', 'service_account', 'client_secret', 'client-secret'))):
        raise KnowledgeError('진행 기록은 인증 자료와 구분되는 JSON 파일로 지정하세요.')
    resume = journal.is_file()
    if resume:
        plan = json.loads(journal.read_text(encoding='utf-8'))
        validate_plan(plan, data_dir, output_dir, model_dir, store is not None)
    else:
        plan = file_plan(data_dir, output_dir, model_dir)
        plan.update(database=store is not None, model_dir=str(safe_path(model_dir)) if model_dir else None,
                    token=uuid4().hex)
    if any(journal.is_relative_to(Path(p)) for pair in plan['roots'] for p in pair):
        raise KnowledgeError('진행 기록은 전환 루트 밖에 지정하세요.')
    if plan.get('model_dir') and journal.is_relative_to(Path(plan['model_dir'])):
        raise KnowledgeError('진행 기록은 모델 루트 밖에 지정하세요.')
    if not (data_dir or output_dir or model_dir or store):
        raise KnowledgeError('전환할 대상을 지정하세요.')

    def check_database(conn):
        state, versions, identity = database_preflight(conn, plan['roots'])
        if resume and plan.get('database_identity') != identity:
            raise KnowledgeError('진행 기록의 DB 또는 스키마가 현재 연결과 다릅니다.')
        pending = {v for v in versions if v.startswith(PENDING)}
        expected = {PENDING, PENDING + ':' + plan['token']}
        if state == 'current' and pending:
            if not resume or pending != expected:
                raise KnowledgeError('다른 전환의 DB 진행 표시가 있습니다.')
        if resume and state == 'current' and not pending:
            before_database = plan.get('database_initial_state') == 'current' and plan['phase'] in {'planned', 'staged'}
            if not before_database and plan['phase'] not in {'published', 'complete'}:
                raise KnowledgeError('진행 기록에 대응하는 DB 전환 표시가 없습니다.')
            if not before_database:
                validate_published(plan)
        if resume and state == 'legacy' and plan['phase'] in {'database', 'files', 'published', 'complete'}:
            raise KnowledgeError('진행 기록보다 이전 DB입니다. 같은 시점의 백업을 복원하세요.')
        return state, identity

    # 검사 모드는 잠금 파일·진행 기록·staging을 전혀 만들지 않는다.
    if not apply:
        if store:
            with store.transaction(mode='read') as conn:
                check_database(conn)
        return {'files': len(plan['files']), 'folders': len(plan['renames']), 'database': bool(store), 'apply': False}
    if not backup_confirmed:
        raise KnowledgeError('서비스 종료와 DB·파일 백업 후 --backup-confirmed를 지정하세요.')
    with ExitStack() as stack:
        stack.enter_context(process_locks())
        if store:
            from psycopg.rows import dict_row
            guard = stack.enter_context(store.connect(**store.config.connection, row_factory=dict_row))
            if not guard.execute('SELECT pg_try_advisory_lock(72410635) AS acquired').fetchone()['acquired']:
                raise KnowledgeError('공개 백엔드를 먼저 종료하세요.')
            # 충돌과 이력 오류는 journal이나 파일 변경 전에 거절한다.
            with store.transaction(mode='maintenance') as conn:
                conn.execute('SELECT pg_advisory_xact_lock(72410631)')
                state, identity = check_database(conn)
            plan['database_identity'] = identity
            if not resume:
                plan['database_initial_state'] = state
        markers = marker_paths(plan)
        for marker in markers:
            if marker.exists() and (not resume or marker.read_text(encoding='utf-8') != plan['token']):
                raise KnowledgeError('다른 파일 전환의 진행 표시가 있습니다.')
        if not resume:
            write_journal(journal, plan)
        for marker in markers:
            if not marker.exists():
                with marker.open('x', encoding='utf-8') as stream:
                    stream.write(plan['token']); stream.flush(); os.fsync(stream.fileno())
        if plan['phase'] == 'planned':
            for row in plan['files']:
                source, stage = safe_path(row['source']), safe_path(row['stage'])
                if checksum(source) != row['before']:
                    raise KnowledgeError('검사 후 원본이 변경되었습니다.')
                content = row.get('content')
                if content is None:
                    if source.name == 'magi_model_revision.json':
                        with source.open('r', encoding='utf-8', newline='') as stream:
                            content = stream.read()
                    else:
                        content = json.dumps(transform(json.loads(source.read_text(encoding='utf-8')), plan['roots']), ensure_ascii=False, indent=2) + '\n'
                if not stage.exists():
                    with stage.open('x', encoding='utf-8', newline='') as stream:
                        stream.write(content); stream.flush(); os.fsync(stream.fileno())
                if checksum(stage) != row['after']:
                    raise KnowledgeError('전환 임시 파일의 해시가 다릅니다.')
            plan['phase'] = 'staged'; write_journal(journal, plan)
        if store:
            with store.transaction(mode='maintenance') as conn:
                conn.execute('SELECT pg_advisory_xact_lock(72410631)')
                state, identity = check_database(conn)
                if state == 'legacy':
                    run_migrations(conn, state, pending_files=True)
                    conn.execute('INSERT INTO schema_versions VALUES (%s)', (PENDING + ':' + plan['token'],))
                    convert_database(conn, plan['roots'])
                elif not resume or (plan.get('database_initial_state') == 'current' and
                                    not conn.execute('SELECT 1 FROM schema_versions WHERE version=%s', (PENDING,)).fetchone()):
                    conn.execute('INSERT INTO schema_versions VALUES (%s)', (PENDING,))
                    conn.execute('INSERT INTO schema_versions VALUES (%s)', (PENDING + ':' + plan['token'],))
                    convert_database(conn, plan['roots'])
        if plan['phase'] in {'staged', 'database', 'files'}:
            plan['phase'] = 'database'; write_journal(journal, plan)
            publish(plan, journal)
        validate_published(plan)
        if store:
            with store.transaction(mode='maintenance') as conn:
                conn.execute('DELETE FROM schema_versions WHERE version=ANY(%s)',
                             ([PENDING, PENDING + ':' + plan['token']],))
        for marker in marker_paths(plan):
            if marker.exists():
                if marker.read_text(encoding='utf-8') != plan['token']:
                    raise KnowledgeError('전환 완료 표시가 다른 작업과 충돌합니다.')
                marker.unlink()
        plan['phase'] = 'complete'; write_journal(journal, plan)
    return {'files': len(plan['files']), 'folders': len(plan['renames']), 'database': bool(store), 'apply': True}


def main():
    parser = argparse.ArgumentParser(description='MAGI 접두사 전환; 기본은 읽기 전용 검사')
    for name in ('data-dir', 'output-dir', 'model-dir', 'journal'):
        parser.add_argument('--' + name)
    parser.add_argument('--database', action='store_true')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-confirmed', action='store_true')
    args = vars(parser.parse_args())
    database = args.pop('database')
    try:
        store = None
        if database:
            from backend.knowledge.store import KnowledgeStore
            config = KnowledgeConfig.from_env(allow_legacy_model=True)
            if config is None: raise KnowledgeError('새 이름의 DB 환경 변수를 주입하세요.')
            store = KnowledgeStore(config)
        print(json.dumps(transition(store=store, **args), ensure_ascii=False))
    except Exception as exc:
        # 파일·DB 예외 원문에는 사용자 내용이나 접속 정보가 포함될 수 있다.
        print(json.dumps({'error': str(exc) if isinstance(exc, KnowledgeError) else '전환 실패: 백업과 진행 기록을 확인하세요.'}, ensure_ascii=False))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
