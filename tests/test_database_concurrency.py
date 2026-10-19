"""사용자 DB와 분리된 임시 PostgreSQL의 실제 연결로 잠금·경합을 검증한다."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
from uuid import uuid4

import pytest

from backend.access.context import AccessError
from backend.access.store import AccessStore
from backend.knowledge.config import KnowledgeConfig, KnowledgeError
from backend.knowledge.store import KnowledgeStore


@pytest.fixture(scope='module')
def postgres(tmp_path_factory):
    binary = shutil.which('initdb')
    if binary is None:
        candidate = Path(tempfile.gettempdir()) / 'magi-postgres-validation/pgsql/bin/initdb.exe'
        if candidate.is_file():
            binary = str(candidate)
    if binary is None:
        pytest.skip('임시 PostgreSQL 실행에 필요한 initdb/pg_ctl이 없습니다.')
    root = tmp_path_factory.mktemp('magi-postgres')
    data = root / 'data'
    ctl = Path(binary).with_name('pg_ctl.exe' if binary.endswith('.exe') else 'pg_ctl')
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    subprocess.run([binary, '-D', str(data), '-A', 'trust', '-U', 'magi_test', '-E', 'UTF8', '--locale=C'],
                   check=True, capture_output=True, creationflags=flags, timeout=30)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    subprocess.run([str(ctl), '-D', str(data), '-l', str(root/'server.log'), '-w', '-t', '30',
                    '-o', f'-h 127.0.0.1 -p {port} -c shared_buffers=32MB -c max_connections=12', 'start'],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   creationflags=flags, timeout=40)
    try:
        yield {'host': '127.0.0.1', 'port': port, 'dbname': 'postgres', 'user': 'magi_test',
               'password': '', 'passfile': str(root/'no-password-file'), 'connect_timeout': 3}
    finally:
        subprocess.run([str(ctl), '-D', str(data), '-w', '-t', '30', '-m', 'fast', 'stop'],
                       check=True, capture_output=True, creationflags=flags, timeout=40)


@pytest.fixture
def sql_store(postgres):
    import psycopg
    schema = 'test_' + uuid4().hex
    with psycopg.connect(**postgres) as c:
        c.execute(f'CREATE SCHEMA {schema}')
    config = KnowledgeConfig({**postgres, 'options': f'-c search_path={schema},public'})
    return KnowledgeStore(config)


def test_readers_overlap_writer_serializes_and_maintenance_excludes(sql_store):
    store = sql_store
    with ThreadPoolExecutor(max_workers=3) as pool:
        release = threading.Event()
        entered = threading.Event()
        def read():
            with store.transaction(mode='read') as c:
                entered.set()
                assert release.wait(5)
                return c.execute('SELECT 1 AS value').fetchone()['value']
        reader = pool.submit(read)
        try:
            assert entered.wait(3)
            # 별도 읽기 연결은 첫 번째 읽기가 끝나기 전에 결과를 반환한다.
            with store.transaction(mode='read') as c:
                assert c.execute('SELECT 2 AS value').fetchone()['value'] == 2
            with store.transaction() as c:
                assert c.execute('SELECT 3 AS value').fetchone()['value'] == 3
            entered_maintenance = threading.Event()
            def maintain():
                with store.transaction(mode='maintenance'):
                    entered_maintenance.set()
            maintenance = pool.submit(maintain)
            assert not entered_maintenance.wait(.2)
        finally:
            release.set()
        assert reader.result(timeout=5) == 1
        maintenance.result(timeout=5)
        assert entered_maintenance.is_set()

        # 별도 저장소 인스턴스에서도 DB의 쓰기 잠금이 동작해야 한다.
        other = KnowledgeStore(store.config)
        wrote = threading.Event()
        def write():
            with other.transaction():
                wrote.set()
        with store.transaction():
            writer = pool.submit(write)
            assert not wrote.wait(.2)
        writer.result(timeout=5)
        assert wrote.is_set()


def test_connection_bound_nested_modes_and_rollback_release(sql_store):
    import psycopg
    active = maximum = 0
    guard = threading.Lock()
    class Connection:
        def __init__(self, **kwargs):
            nonlocal active, maximum
            self.connection = psycopg.connect(**kwargs)
            with guard:
                active += 1
                maximum = max(maximum, active)
        def __enter__(self):
            return self.connection.__enter__()
        def __exit__(self, *args):
            nonlocal active
            try:
                return self.connection.__exit__(*args)
            finally:
                with guard:
                    active -= 1
    store = KnowledgeStore(sql_store.config, connect=Connection)
    release = threading.Event()
    two = threading.Barrier(3)
    def read(block=False):
        with store.transaction(mode='read') as c:
            with store.transaction(mode='read') as same:
                assert same is c
            if block:
                two.wait(timeout=4)
                assert release.wait(5)
            return c.execute('SELECT 1 AS value').fetchone()['value']
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(read, True)
        second = pool.submit(read, True)
        try:
            two.wait(timeout=4)
            third = pool.submit(read)
            assert not third.done()
            assert active == maximum == 2
        finally:
            release.set()
        assert [f.result(timeout=5) for f in (first, second, third)] == [1, 1, 1]
    assert maximum == 2 and active == 0
    with store.transaction(mode='read'):
        with pytest.raises(KnowledgeError, match='승격'):
            with store.transaction():
                pass
    with pytest.raises(KnowledgeError):
        with store.transaction(mode='read') as c:
            c.execute('CREATE TABLE forbidden(id integer)')
    with pytest.raises(KnowledgeError):
        with store.transaction(mode='maintenance') as c:
            c.execute('SELECT 1/0')
    # rollback된 트랜잭션의 연결 슬롯과 두 잠금 모두 반환되어야 한다.
    with store.transaction() as c:
        assert c.execute('SELECT 1 AS value').fetchone()['value'] == 1


def test_multi_query_read_keeps_one_snapshot_while_writer_commits(sql_store):
    with sql_store.transaction() as c:
        c.execute('CREATE TABLE versions(value integer)')
        c.execute('INSERT INTO versions VALUES (1)')
    other = KnowledgeStore(sql_store.config)
    def update():
        with other.transaction() as c:
            c.execute('UPDATE versions SET value=2')
    with ThreadPoolExecutor(max_workers=1) as pool:
        with sql_store.transaction(mode='read') as c:
            assert c.execute('SELECT value FROM versions').fetchone()['value'] == 1
            pool.submit(update).result(timeout=5)
            assert c.execute('SELECT value FROM versions').fetchone()['value'] == 1
    with sql_store.transaction(mode='read') as c:
        assert c.execute('SELECT value FROM versions').fetchone()['value'] == 2


def test_global_cost_limit_under_concurrent_reservations(sql_store):
    with sql_store.transaction(mode='maintenance') as c:
        c.execute('CREATE TABLE magi_jobs(id text PRIMARY KEY)')
        c.execute(Path('backend/knowledge/migrations/005.sql').read_text(encoding='utf-8'))
    access = AccessStore(sql_store, clock=lambda: 1800000000)
    sid = access.login('fake-subject', 'fake-pepper')
    user = access.session(sid)
    with sql_store.transaction() as c:
        c.execute('UPDATE magi_users SET daily_usd=10')
        c.execute('UPDATE magi_service_settings SET daily_usd=1')
        generation = access.acquire(c, user['id'], 'test-job')
    barrier = threading.Barrier(2)
    def reserve():
        separate = AccessStore(KnowledgeStore(sql_store.config), clock=access.clock)
        barrier.wait(timeout=3)
        try:
            return separate.reserve(user['id'], 'test-job', generation, 'fake-model', Decimal('.75'))
        except AccessError as exc:
            assert exc.code == 'quota'
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(reserve) for _ in range(2)]
        assert sum(f.result(timeout=5) is not None for f in results) == 1
    with sql_store.transaction(mode='read') as c:
        assert c.execute('SELECT sum(reserved) AS total FROM magi_daily_usage').fetchone()['total'] == Decimal('.75')


def test_deleted_nodes_are_not_recreated_by_inflight_chunk_completion(sql_store):
    with sql_store.transaction(mode='maintenance') as c:
        c.execute('''CREATE TABLE magi_nodes(id text PRIMARY KEY,job_id text);
                     CREATE TABLE magi_chunk_sets(node_id text,model_id text,completed boolean,UNIQUE(node_id,model_id));
                     CREATE TABLE magi_chunks(id text,node_id text);
                     CREATE TABLE magi_chunk_vectors(chunk_id text,model_id text);
                     CREATE TABLE magi_embedding_queue(node_id text,status text);
                     CREATE TABLE magi_embeddings(node_id text);
                     CREATE TABLE magi_edges(id text,source text,target text);
                     CREATE TABLE magi_admissions(result jsonb);
                     CREATE TABLE magi_jobs(id text);
                     CREATE TABLE magi_projects(id text);
                     CREATE TABLE magi_artifacts(job_id text);
                     CREATE TABLE magi_snapshots(job_id text);
                     CREATE TABLE magi_executions(job_id text);
                     CREATE TABLE magi_deleted_jobs(id text PRIMARY KEY);
                     CREATE TABLE magi_deleted_nodes(id text PRIMARY KEY);
                     INSERT INTO magi_nodes VALUES ('node','job');
                     INSERT INTO magi_jobs VALUES ('job');''')
    separate = KnowledgeStore(sql_store.config)
    started = threading.Barrier(3)
    def complete():
        started.wait(timeout=3)
        return separate.complete_chunks('node', 'model', 0)
    def save():
        started.wait(timeout=3)
        return separate.save_chunk({'id': 'model', 'dimensions': 2}, {'node_id': 'node'}, [1.0, 0.0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        with sql_store.transaction(mode='maintenance') as c:
            sql_store.cleanup_delete(c, {'jobs': [{'id': 'job'}], 'projects': []})
            completion = pool.submit(complete)
            saving = pool.submit(save)
            started.wait(timeout=3)
            with pytest.raises(TimeoutError):
                completion.result(timeout=.2)
        assert completion.result(timeout=5) is False
        assert saving.result(timeout=5) is False
    with sql_store.transaction(mode='read') as c:
        assert c.execute('SELECT count(*) AS total FROM magi_chunk_sets').fetchone()['total'] == 0
        assert c.execute("SELECT id FROM magi_deleted_nodes WHERE id='node'").fetchone()
