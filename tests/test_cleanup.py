"""사용자 DB와 무관한 임시 기록으로 영구 삭제·복구 계약을 검증한다."""

import json
import threading
from types import SimpleNamespace

import pytest

from backend.server.cleanup import Cleanup, CleanupConflict
from test_knowledge_postgres import store


def manager(tmp_path, store=None):
    value = SimpleNamespace(data_dir=tmp_path, lock=threading.RLock(), jobs={},
                            _activities={}, _document_locks={}, knowledge=SimpleNamespace(store=store) if store else None)
    value.cleanup = Cleanup(value)
    return value


def file_job(manager, ident, **data):
    path = manager.data_dir / ident
    path.mkdir()
    (path / 'job.json').write_text(json.dumps({'id': ident, 'status': 'FINALIZED', **data}), encoding='utf-8')
    (path / 'old.md').write_text('이전 계약도 삭제 가능', encoding='utf-8')
    return path


def test_file_scope_expiry_change_busy_and_confirmation(tmp_path):
    m = manager(tmp_path)
    first, second = 'a' * 32, 'b' * 32
    path = file_job(m, first)
    file_job(m, second)
    (tmp_path / 'unknown').mkdir()
    (tmp_path / ('c' * 32)).mkdir()
    op = m.cleanup.preview({'scope': 'jobs', 'ids': [first]})
    (path / 'old.md').write_text('changed', encoding='utf-8')
    with pytest.raises(CleanupConflict, match='바뀌'):
        m.cleanup.execute({'id': op['id']})
    op = m.cleanup.preview({'scope': 'jobs', 'ids': [first]})
    m._activities[first] = 1
    with pytest.raises(CleanupConflict, match='실행'):
        m.cleanup.execute({'id': op['id']})
    m._activities.clear()
    op['expires_at'] = 0
    m.cleanup.write(op)
    with pytest.raises(CleanupConflict, match='만료'):
        m.cleanup.execute({'id': op['id']})
    op = m.cleanup.preview({'scope': 'jobs', 'ids': [first]})
    assert m.cleanup.execute({'id': op['id']})['state'] == 'completed'
    assert m.cleanup.execute({'id': op['id']})['state'] == 'completed'
    assert not path.exists() and (tmp_path / second).exists()
    op = m.cleanup.preview({'scope': 'all'})
    assert 'c' * 32 in op['skipped']
    with pytest.raises(ValueError):
        m.cleanup.execute({'id': op['id']})
    m.cleanup.execute({'id': op['id'], 'confirmation': '전체 기록 삭제'})
    assert (tmp_path / 'unknown').exists()
    assert m.cleanup.catalog()['jobs'] == []


def test_file_failure_retry_and_restart(tmp_path, monkeypatch):
    m = manager(tmp_path)
    ident = 'a' * 32
    path = file_job(m, ident)
    op = m.cleanup.preview({'scope': 'all'})
    import backend.server.cleanup as module
    original = module.shutil.rmtree
    monkeypatch.setattr(module.shutil, 'rmtree', lambda path: (_ for _ in ()).throw(OSError('locked')))
    result = m.cleanup.execute({'id': op['id'], 'confirmation': '전체 기록 삭제'})
    assert result['state'] == 'files_pending' and not path.exists()
    monkeypatch.setattr(module.shutil, 'rmtree', original)
    restarted = manager(tmp_path)
    restarted.cleanup.recover()
    assert restarted.cleanup.load(op['id'])['state'] == 'completed'
    assert restarted.cleanup.catalog()['jobs'] == []


def test_project_and_cross_job_vectors_all_generations(store, tmp_path):
    m = manager(tmp_path, store)
    projects = [store.create_project(name) for name in ('삭제', '유지')]
    jobs = [{'id': c * 32, 'project_id': p['id'], 'status': 'FINALIZED'} for c, p in zip('ab', projects)]
    for job in jobs:
        store.commit_stage(job, job['id'], 'spec_compile', {'user_request': job['id']}, {})
        file_job(m, job['id'])
    with store.transaction() as conn:
        nodes = conn.execute('SELECT id,job_id FROM magi_nodes ORDER BY job_id').fetchall()
        first, second = nodes[0]['id'], nodes[1]['id']
        conn.execute("INSERT INTO magi_edges(id,source,target,kind) VALUES ('cross',%s,%s,'reused')", (first, second))
        for model in ('old', 'new'):
            conn.execute('INSERT INTO magi_models VALUES (%s,3,512,false)', (model,))
            conn.execute("INSERT INTO magi_embeddings VALUES (%s,%s,'hash','[1,0,0]')", (first, model))
        conn.execute("INSERT INTO magi_chunks VALUES ('chunk',%s,0,'rule','','body','input','hash','[]')", (first,))
        for model in ('old', 'new'):
            conn.execute("INSERT INTO magi_chunk_vectors VALUES ('chunk',%s,'[1,0,0]')", (model,))
    op = m.cleanup.preview({'scope': 'projects', 'ids': [projects[0]['id']]})
    assert op['external_references'] == 1
    assert op['counts']['magi_embeddings'] == 2 and op['counts']['magi_chunk_vectors'] == 2
    m.cleanup.execute({'id': op['id']})
    assert [j['id'] for j in store.jobs()] == [jobs[1]['id']]
    assert store.projects() == [projects[1]]
    with store.transaction() as conn:
        for table in ('magi_chunks', 'magi_chunk_vectors', 'magi_embeddings', 'magi_edges'):
            assert conn.execute(f'SELECT count(*) AS total FROM {table}').fetchone()['total'] == 0
        assert conn.execute('SELECT count(*) AS total FROM magi_models').fetchone()['total'] == 2
    with pytest.raises(ValueError, match='삭제'):
        store.save_job(jobs[0])
    assert store.complete_chunks(first, 'new', 0) is False
    assert store.save_chunk({'id': 'new', 'dimensions': 3}, {'node_id': first}, [1., 0., 0.]) is False
    with store.transaction() as conn:
        store._edge(conn, first, second, 'reused')
        assert conn.execute('SELECT count(*) AS total FROM magi_edges').fetchone()['total'] == 0
    op = m.cleanup.preview({'scope': 'all'})
    m.cleanup.execute({'id': op['id'], 'confirmation': '전체 기록 삭제'})
    assert not store.jobs() and not store.projects()


def test_db_rollback_and_commit_marker_recovery(store, tmp_path, monkeypatch):
    m = manager(tmp_path, store)
    project = store.create_project('보존')
    job = {'id': 'a' * 32, 'project_id': project['id'], 'status': 'FINALIZED'}
    store.save_job(job)
    path = file_job(m, job['id'])
    op = m.cleanup.preview({'scope': 'jobs', 'ids': [job['id']]})
    original = store.cleanup_delete
    def fail(conn, inventory):
        original(conn, inventory)
        raise RuntimeError('rollback')
    monkeypatch.setattr(store, 'cleanup_delete', fail)
    with pytest.raises(RuntimeError):
        m.cleanup.execute({'id': op['id']})
    assert path.is_dir() and len(store.jobs()) == 1
    monkeypatch.setattr(store, 'cleanup_delete', original)
    op = m.cleanup.preview({'scope': 'jobs', 'ids': [job['id']]})
    op['state'] = 'prepared'
    m.cleanup.write(op)
    m.cleanup.quarantine(op)
    with store.transaction() as conn:
        inventory = store.cleanup_inventory(conn, 'jobs', [job['id']])
        store.cleanup_delete(conn, inventory)
        conn.execute('INSERT INTO magi_cleanup_commits VALUES (%s)', (op['id'],))
    manager(tmp_path, store).cleanup.recover()
    assert not store.jobs() and not path.exists()


def test_new_project_member_invalidates_preview(store, tmp_path):
    m = manager(tmp_path, store)
    p = store.create_project('프로젝트')
    op = m.cleanup.preview({'scope': 'projects', 'ids': [p['id']]})
    store.save_job({'id': 'a' * 32, 'project_id': p['id'], 'status': 'FINALIZED'})
    with pytest.raises(CleanupConflict, match='바뀌'):
        m.cleanup.execute({'id': op['id']})
    assert len(store.jobs()) == 1


def test_translation_and_terminal_activity_block_cleanup(tmp_path):
    from backend.server.cleanup import tracked
    m = manager(tmp_path)
    ident = 'a' * 32
    file_job(m, ident)
    m.jobs[ident] = {'id': ident, 'status': 'FINALIZED'}
    m._get_locked = lambda key: m.jobs[key]
    entered, release = threading.Event(), threading.Event()
    @tracked
    def document(self, ident):
        entered.set()
        assert release.wait(5)
    worker = threading.Thread(target=document, args=(m, ident))
    worker.start()
    try:
        assert entered.wait(5)
        with pytest.raises(CleanupConflict, match='실행'):
            m.cleanup.preview({'scope': 'all'})
    finally:
        release.set()
        worker.join(5)
    assert m.cleanup.preview({'scope': 'all'})['counts']['jobs'] == 1


def test_linked_job_directory_is_skipped_without_following(tmp_path, monkeypatch):
    from pathlib import Path
    m = manager(tmp_path)
    ident = 'a' * 32
    path = file_job(m, ident)
    monkeypatch.setattr(Path, 'is_junction', lambda self: self == path, raising=False)
    op = m.cleanup.preview({'scope': 'all'})
    assert op['targets'] == [] and ident in op['skipped']
    m.cleanup.execute({'id': op['id'], 'confirmation': '전체 기록 삭제'})
    assert path.is_dir()
