"""후속 대화의 ID·완료본·실패 복구를 외부 호출 없이 검증한다."""

import json
import asyncio
from unittest.mock import Mock

import pytest

from backend.errors import ConversationUnavailableError
from backend.infrastructure.artifact_writer import ArtifactWriter
from backend.infrastructure.conversation_state import PATH
from backend.models import CompletionResult, InterviewResponse, LockResponse
from backend.server.cleanup import CleanupConflict
from backend.server.job_manager import JobManager
from backend.services.completed_specs import restore_completed_cache
from test_review_decisions import DecisionProvider, engine_for, read_state
from test_knowledge_postgres import store


class SessionProvider(DecisionProvider):
    def __init__(self):
        super().__init__([[], [], [], []])
        self.created = 0
        self.ids = []
        self.feedback = ''

    def create_conversation(self):
        self.created += 1
        return f'conv_session{self.created}'

    def complete_result(self, messages, **kwargs):
        self.ids.append(kwargs['conversation_id'])
        for message in messages:
            if message['content'].startswith('Canonical context:\n'):
                sources = json.loads(message['content'].split('\n', 1)[1])['sources']
                self.feedback = next((key for key, item in sources.items() if 'user_feedback' in item.get('roles', [item['type']])), '')
        result = super().complete_result(messages, **kwargs)
        if kwargs['text_format'] is LockResponse:
            # 실제 사용자 후속 원문을 제품 요구사항으로 보존한다.
            if self.feedback:
                result.parsed.mandatory_requirements[0].sources.append(self.feedback)
        return result


def completed(tmp_path):
    provider = SessionProvider()
    engine = engine_for(provider)
    assert engine.generate_from_text(text='메모를 저장해주세요', output_dir=str(tmp_path)).status == 'PASS_PENDING_USER_APPROVAL'
    assert engine.approve(str(tmp_path)).status == 'FINALIZED'
    return engine, provider


def test_new_generation_uses_distinct_conversations_and_state(tmp_path):
    provider = SessionProvider()
    engine = engine_for(provider)
    paths = [tmp_path / 'first', tmp_path / 'second']
    for path in paths:
        assert engine.generate_from_text(text='메모를 저장해주세요', output_dir=str(path)).status == 'PASS_PENDING_USER_APPROVAL'
    states = [read_state(path) for path in paths]
    conversations = [json.loads((path / PATH).read_text(encoding='utf-8'))['conversation_id'] for path in paths]
    assert len(set(conversations)) == 2 and provider.created == 2
    assert states[0]['run_id'] != states[1]['run_id']
    assert all(state['revision_history'] == [] and state['latest_completed'] is None for state in states)


def test_question_answer_approval_followup_share_conversation(tmp_path):
    class Provider(SessionProvider):
        def complete_result(self, messages, **kwargs):
            result = super().complete_result(messages, **kwargs)
            if kwargs['text_format'] is InterviewResponse and self.calls.count(InterviewResponse) == 1:
                parsed = InterviewResponse.model_validate({**result.parsed.model_dump(),
                    'blocking_questions': [{'question_id': 'PRODUCT-003', 'question': '저장 방식은 무엇인가요?'}], 'pre_answers': []})
                return CompletionResult(text='', parsed=parsed, response_id=result.response_id)
            return result
    provider = Provider()
    engine = engine_for(provider)
    assert engine.generate_from_text(text='메모를 저장해주세요', output_dir=str(tmp_path)).status == 'NEEDS_USER_INPUT'
    question = read_state(tmp_path)['blocking_questions'][0]
    assert engine.answer(str(tmp_path), answers=[{'question_id': 'PRODUCT-003', 'question': question, 'answer': '오프라인 저장'}]).status == 'PASS_PENDING_USER_APPROVAL'
    engine.approve(str(tmp_path))
    original = read_state(tmp_path)
    reference = original['latest_completed']
    snapshot = (tmp_path / reference['path']).read_text(encoding='utf-8')
    feedback = tmp_path / 'feedback.txt'
    feedback.write_text('메모를 저장해주세요', encoding='utf-8')
    assert engine.revise(output_dir=str(tmp_path), feedback_path=str(feedback)).status == 'PASS_PENDING_USER_APPROVAL'
    assert read_state(tmp_path)['latest_completed'] == reference
    assert (tmp_path / reference['path']).read_text(encoding='utf-8') == snapshot
    assert engine.approve(str(tmp_path)).status == 'FINALIZED'
    assert provider.created == 1 and set(provider.ids) == {'conv_session1'}
    assert any(answer['answer'] == '오프라인 저장' for answer in read_state(tmp_path)['requirement_lock_sheet']['user_answers'])
    current = read_state(tmp_path)
    assert current['original_user_request'] == original['original_user_request']
    assert current['revision_history'] == ['메모를 저장해주세요']
    assert len(list((tmp_path / 'completed').glob('*.json'))) >= 2


def test_resume_keeps_historical_model_record_but_calls_only_luna(tmp_path):
    engine,provider=completed(tmp_path)
    history=tmp_path/'state/private_model_assignments.json'
    legacy=json.dumps({'compiler':{'provider':'openai','model':'historical-model'}})
    history.write_text(legacy,encoding='utf-8')
    snapshot=read_state(tmp_path)['latest_completed']
    document=(tmp_path/snapshot['path']).read_bytes()
    original=provider.complete_result
    models=[]
    def capture(messages,**kwargs):
        models.append(kwargs['model'])
        return original(messages,**kwargs)
    provider.complete_result=capture
    feedback=tmp_path/'feedback.txt'
    feedback.write_text('메모를 저장해주세요',encoding='utf-8')
    assert engine.revise(output_dir=str(tmp_path),feedback_path=str(feedback)).status=='PASS_PENDING_USER_APPROVAL'
    assert models and set(models)=={'gpt-6-luna'}
    assert history.read_text(encoding='utf-8')==legacy
    assert (tmp_path/snapshot['path']).read_bytes()==document


@pytest.mark.parametrize('state', [None, {'conversation_id': 'bad'}, {'conversation_id': 'conv_x', 'status': 'pending', 'fingerprints': {}}])
def test_lost_corrupt_uncertain_conversation_never_restarts(tmp_path, state):
    engine, provider = completed(tmp_path)
    before = len(provider.ids)
    path = tmp_path / PATH
    if state is None:
        path.unlink()
    else:
        path.write_text(json.dumps(state), encoding='utf-8')
    feedback = tmp_path / 'feedback.txt'
    feedback.write_text('변경 요청', encoding='utf-8')
    with pytest.raises(ConversationUnavailableError):
        engine.revise(output_dir=str(tmp_path), feedback_path=str(feedback))
    assert len(provider.ids) == before and provider.created == 1
    assert read_state(tmp_path)['status'] == 'FINALIZED'


def test_continue_api_identity_conflict_and_restore(tmp_path):
    m = JobManager(tmp_path)
    try:
        m._submit_locked = Mock()
        job = m.create('메모를 저장해주세요')
        root = m.root(job['id'])
        engine, provider = completed(root)
        m.jobs[job['id']]['status'] = 'FINALIZED'
        m._save_locked(m.jobs[job['id']])
        old_execution = m.jobs[job['id']]['execution_id']
        m._activities[job['id']] = 1
        with pytest.raises(CleanupConflict):
            m.continue_session(job['id'], '메모를 저장해주세요', old_execution)
        m._activities[job['id']] = 0
        with pytest.raises(CleanupConflict):
            m.continue_session(job['id'], '메모를 저장해주세요', 'wrong')
        result = m.continue_session(job['id'], '메모를 저장해주세요', old_execution)
        assert result['id'] == job['id'] and result['execution_id'] != old_execution
        assert result['request'] == job['request'] and result['action'] == 'revise'
        with pytest.raises(CleanupConflict):
            m.continue_session(job['id'], '중복 요청', old_execution)
        state = engine._load_state(ArtifactWriter(root))
        (root / 'final/FINAL_AGENT_SPEC.md').write_text('interrupted cache', encoding='utf-8')
        restore_completed_cache(ArtifactWriter(root), state)
        assert (root / 'final/FINAL_AGENT_SPEC.md').read_text(encoding='utf-8') != 'interrupted cache'
        assert m.public(job['id'])['session_events'][-1]['input']['feedback'] == '메모를 저장해주세요'
        reference = read_state(root)['latest_completed']
        assert m.document(job['id'], reference['id'], 'en')['content'] == (root / 'final/FINAL_AGENT_SPEC.md').read_text(encoding='utf-8')
    finally:
        m.close()


def test_approval_storage_failure_keeps_previous_completed(tmp_path, monkeypatch):
    engine, provider = completed(tmp_path)
    feedback = tmp_path / 'feedback.txt'
    feedback.write_text('메모를 저장해주세요', encoding='utf-8')
    engine.revise(output_dir=str(tmp_path), feedback_path=str(feedback))
    before = read_state(tmp_path)
    document = (tmp_path / 'final/FINAL_AGENT_SPEC.md').read_text(encoding='utf-8')
    monkeypatch.setattr(engine, '_persist_state', Mock(side_effect=OSError('test storage failure')))
    with pytest.raises(OSError):
        engine.approve(str(tmp_path))
    assert read_state(tmp_path) == before
    assert (tmp_path / 'final/FINAL_AGENT_SPEC.md').read_text(encoding='utf-8') == document


def test_queued_continuation_restart_requires_explicit_input_and_keeps_request(tmp_path):
    manager = JobManager(tmp_path)
    manager._submit_locked = Mock()
    try:
        job = manager.create('메모를 저장해주세요')
        completed(manager.root(job['id']))
        manager.jobs[job['id']]['status'] = 'FINALIZED'
        manager._save_locked(manager.jobs[job['id']])
        queued = manager.continue_session(job['id'], '저장 검증을 보완해주세요', job['execution_id'])
    finally:
        manager.close()
    restarted = JobManager(tmp_path)
    restarted._submit_locked = Mock()
    try:
        assert restarted.get(job['id'])['status'] == 'interrupted'
        assert not restarted._submit_locked.called
        public = restarted.public(job['id'])
        assert public['can_continue']
        assert public['session_events'][-1]['input']['feedback'] == '저장 검증을 보완해주세요'
        result = restarted.continue_session(job['id'], '저장 검증을 보완해주세요', queued['execution_id'])
        assert result['id'] == job['id'] and result['execution_id'] != queued['execution_id']
    finally:
        restarted.close()


def test_postgres_continue_reapprove_and_restart_keep_session(store, tmp_path):
    from backend.knowledge.runtime import KnowledgeService
    from backend.knowledge.embedding import LocalEmbedding
    provider = SessionProvider()
    service = KnowledgeService(store, LocalEmbedding(None))
    service.schedule = lambda: None
    manager = JobManager(tmp_path, engine_factory=lambda: engine_for(provider), knowledge=service)
    manager._submit_locked = Mock()
    ident = None
    try:
        job = manager.create('메모를 저장해주세요')
        ident = job['id']
        manager._run(ident, 'generate', None)
        assert manager.get(ident)['status'] == 'PASS_PENDING_USER_APPROVAL'
        manager.action(ident, 'approve', None)
        manager._run(ident, 'approve', None)
        before = manager.summary(ident)
        previous = before['latest_completed']['step_id']
        original = manager.document(ident, previous, 'en')['content']
        manager.continue_session(ident, '메모를 저장해주세요', before['execution_id'])
        manager._run(ident, 'revise', '메모를 저장해주세요')
        assert manager.get(ident)['status'] == 'PASS_PENDING_USER_APPROVAL'
        assert manager.document(ident, previous, 'en')['content'] == original
        manager.action(ident, 'approve', None)
        manager._run(ident, 'approve', None)
        assert manager.get(ident)['status'] == 'FINALIZED'
        assert len(manager.public(ident)['completed_documents']) == 2
        assert len(store.jobs()) == 1 and len(store.action_records(ident)) == 4
    finally:
        manager.close()
    service = KnowledgeService(store, LocalEmbedding(None))
    service.schedule = lambda: None
    restarted = JobManager(tmp_path, knowledge=service)
    try:
        assert restarted.ids() == [ident]
        assert restarted.summary(ident)['can_continue']
        assert restarted.document(ident, previous, 'en')['content'] == original
        assert json.loads((restarted.root(ident) / PATH).read_text(encoding='utf-8'))['conversation_id'] == 'conv_session1'
        assert provider.created == 1
    finally:
        restarted.close()


def test_context_filters_project_before_and_after_graph_expansion():
    from backend.knowledge.runtime import KnowledgeService
    from backend.knowledge.embedding import LocalEmbedding
    store = Mock()
    record = {'id': 'owned', 'project_id': 'project-a', 'job_id': 'job', 'kind': 'spec', 'active': True,
              'body': 'Current project specification.', 'attrs': {'scope': 'product'}}
    other = {**record, 'id': 'other', 'project_id': 'project-b', 'body': 'UNRELATED_PROJECT'}
    store.graph.return_value = {'nodes': [record, other], 'edges': []}
    store.node_records.return_value = {'owned': record, 'other': other}
    service = KnowledgeService(store, LocalEmbedding(None))
    service.search = Mock(return_value={'nodes': [record], 'mode': 'text'})
    try:
        context = service.context('query', project_id='project-a')
        assert [n['id'] for n in context['nodes']] == ['owned']
        service.search.assert_called_once_with('query', project_id='project-a')
        assert store.graph.call_args.kwargs['project_id'] == 'project-a'
    finally:
        service.close()


def test_corrupt_completed_archive_is_read_only_without_blocking_other_sessions(tmp_path):
    manager = JobManager(tmp_path)
    manager._submit_locked = Mock()
    try:
        job = manager.create('메모를 저장해주세요')
        other = manager.create('다른 세션')
        root = manager.root(job['id'])
        completed(root)
        manager.jobs[job['id']]['status'] = 'FINALIZED'
        manager._save_locked(manager.jobs[job['id']])
        reference = read_state(root)['latest_completed']
        (root / reference['path']).write_text('corrupt', encoding='utf-8')
    finally:
        manager.close()
    restarted = JobManager(tmp_path)
    try:
        assert set(restarted.ids()) == {job['id'], other['id']}
        assert restarted.summary(job['id'])['read_only']
        assert not restarted.summary(job['id'])['can_continue']
    finally:
        restarted.close()


def test_continue_gateway_websocket_contract_and_stale_request(tmp_path):
    from backend.server.app import MagiServer
    from gateway.app import create_app
    from websockets.asyncio.server import serve
    async def scenario():
        server = MagiServer(tmp_path)
        server.manager._submit_locked = Mock()
        try:
            job = server.manager.create('메모를 저장해주세요')
            completed(server.manager.root(job['id']))
            server.manager.jobs[job['id']]['status'] = 'FINALIZED'
            server.manager._save_locked(server.manager.jobs[job['id']])
            async with serve(server.handler, '127.0.0.1', 0) as socket_server:
                port = socket_server.sockets[0].getsockname()[1]
                def request():
                    app = create_app({'MAGI_PUBLIC_MODE': False, 'TESTING': True, 'MAGI_SERVER_URL': f'ws://127.0.0.1:{port}'})
                    with app.test_client() as client:
                        assert 'conversation_id' not in json.dumps(client.get('/api/jobs').json)
                        body = {'payload': '메모를 저장해주세요', 'execution_id': job['execution_id']}
                        response = client.post(f"/api/jobs/{job['id']}/continue", json=body)
                        assert response.status_code == 202
                        assert response.json['id'] == job['id'] and response.json['execution_id'] != job['execution_id']
                        assert client.post(f"/api/jobs/{job['id']}/continue", json=body).status_code == 409
                await asyncio.to_thread(request)
        finally:
            server.manager.close()
    asyncio.run(scenario())


def test_session_timeline_preserves_question_then_user_answer(tmp_path):
    from backend.server.execution_history import ExecutionHistory
    history = ExecutionHistory(tmp_path)
    first = history.start_execution('generate', input_data='메모 앱')
    history.terminal(first, 'NEEDS_USER_INPUT', result={'blocking_questions': ['[PRODUCT-003] 저장 방식은 무엇인가요?']})
    second = history.start_execution('answer', input_data=[{'question_id': 'PRODUCT-003', 'question': '저장 방식은 무엇인가요?', 'answer': '오프라인 저장'}])
    history.terminal(second, 'FINALIZED')
    entries = history.conversation()
    assert entries[0]['questions'] == ['[PRODUCT-003] 저장 방식은 무엇인가요?']
    assert entries[1]['input']['answers'][0]['answer'] == '오프라인 저장'
