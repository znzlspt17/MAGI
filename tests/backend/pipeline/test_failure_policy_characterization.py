"""구조 정리 전 예외 전파와 재시도 판단의 관찰 가능한 계약."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from contextlib import asynccontextmanager, nullcontext
from tests.backend.application.async_helpers import run_async

import pytest

from backend.errors import ReviewValidationError, WorkflowPersistenceError, WorkflowExecutionUncertain
from backend.infrastructure.evidence_registry import EvidenceRegistry
from backend.pipeline.agent_workflow import AgentWorkflow
from backend.pipeline.builder import _stage
from backend.server.diagnostics import diagnose_exception


def error_with_cause(outer, inner):
    outer.__cause__ = inner
    return outer


def journal_writer():
    @asynccontextmanager
    async def transaction():
        yield
    return SimpleNamespace(changed={}, state={}, stage_writes=lambda: nullcontext(None),
                           store=SimpleNamespace(transaction=transaction))


@pytest.mark.parametrize(('exc', 'attempts', 'diagnostic_category'), [
    (ReviewValidationError(check='rubric_evidence'), 4, 'response_invalid'),
    (ReviewValidationError(check='rubric_stale'), 1, 'prerequisite_stale'),
    (RuntimeError('failure'), 1, None),
    (error_with_cause(RuntimeError('wrapper'), ReviewValidationError(check='rubric_evidence')), 1, 'response_invalid'),
    (error_with_cause(WorkflowPersistenceError('store'), ReviewValidationError(check='rubric_stale')), 1, 'persistence_failed'),
    (error_with_cause(WorkflowExecutionUncertain('uncertain'), WorkflowPersistenceError('store')), 1, 'execution_uncertain'),
])
@run_async
async def test_correction_and_diagnostic_precedence(exc, attempts, diagnostic_category):
    operation = Mock(side_effect=exc)
    events = []
    with pytest.raises(type(exc)):
        await _stage('checklist_critic', operation, events.append)({})
    assert operation.call_count == attempts
    assert diagnose_exception(exc).get('category') == diagnostic_category
    assert events[-1]['state'] == 'failed'


@pytest.mark.parametrize(('exc', 'calls', 'category', 'marked_failed'), [
    (ReviewValidationError(check='rubric_stale'), 0, 'validation', True),
    (ReviewValidationError(check='rubric_evidence'), 1, 'validation', True),
    (RuntimeError('failure'), 0, 'not_called', True),
    (RuntimeError('failure'), 1, 'call_uncertain', False),
    (WorkflowPersistenceError('store'), 1, 'persistence_failed', False),
])
@run_async
async def test_journal_failure_category_and_replay_boundary(exc, calls, category, marked_failed):
    flow = AgentWorkflow(SimpleNamespace(), None, journal_writer(), EvidenceRegistry())
    flow.journal = SimpleNamespace(get=AsyncMock(), progress=AsyncMock(), failed=AsyncMock(),
                                   begin=AsyncMock(), prepare=AsyncMock(), complete=AsyncMock())
    flow.journal.get.return_value = None
    async def operation(_state):
        from backend.infrastructure.workflow_store import provider_entered
        for _ in range(calls):
            await provider_entered()
        raise exc
    expected = WorkflowExecutionUncertain if category == 'call_uncertain' else type(exc)
    with pytest.raises(expected):
        await flow.durable('checklist_critic', {'run_id': 'job', 'revision': 0, 'plan_history': []}, operation)
    assert flow.journal.progress.call_args.kwargs['category'] == category
    assert flow.journal.failed.called is marked_failed


@pytest.mark.parametrize('started', [True, False])
@run_async
async def test_finished_stage_without_or_with_start_preserves_time_and_diagnostics(started):
    from backend.application.execution_history import ExecutionHistory
    history = ExecutionHistory(SimpleNamespace(usage=AsyncMock(return_value={'attempts': []})))
    data = {'nodes': [], 'executions': []}
    history._load = AsyncMock(return_value=data)
    history._save = AsyncMock()
    execution = await history.start_execution('generate')
    if started:
        await history.stage(execution, 'checklist_critic', 'started')
    await history.stage(execution, 'checklist_critic', 'failed', result={'diagnostic': {
        'error_code': 'REVIEW_VALIDATION_FAILED', 'failed_checks': ['rubric_evidence']}})
    node = data['nodes'][-1]
    assert node['status'] == 'failed'
    assert node['summary'] == '단계 검증에 실패하여 작업을 중단했습니다.'
    assert (node['started_at'] is not None) is started
    assert ('usage' in node) is started
    assert ('attempts' in node['result']['diagnostic']) is started


@pytest.mark.parametrize(('action', 'invalidated'), [
    ('interview', {'requirement_lock_stage', 'spec_compile', 'checklist_critic', 'review_resolution', 'compose_candidate'}),
    ('requirement_lock_stage', {'spec_compile', 'checklist_critic', 'review_resolution', 'compose_candidate'}),
    ('spec_compile', {'checklist_critic', 'review_resolution', 'compose_candidate'}),
    ('checklist_critic', {'review_resolution', 'compose_candidate'}),
    ('review_resolution', set()),
])
@run_async
async def test_normal_completion_invalidates_only_downstream_tasks(monkeypatch, action, invalidated):
    import backend.pipeline.agent_workflow as workflow_module
    from backend.application.execution_history import ExecutionHistory
    monkeypatch.setattr(workflow_module, 'execution_constraints', lambda *_: {'repeated_actions': []})
    monkeypatch.setattr(workflow_module, 'evaluate_execution', lambda *_: SimpleNamespace(allowed_actions={action}, required_action=action))
    monkeypatch.setattr(workflow_module, 'task_signature', lambda *_: 'signature')
    monkeypatch.setattr(ExecutionHistory, 'graph', AsyncMock(return_value={'nodes': []}))
    writer = Mock()
    writer.read_text = AsyncMock(return_value='draft')
    writer.write_text = AsyncMock()
    flow = AgentWorkflow(SimpleNamespace(config=Mock()), Mock(), writer, EvidenceRegistry())
    flow.durable = AsyncMock(return_value={})
    flow.persist = AsyncMock()
    flow._candidate_hash = AsyncMock(return_value='draft-hash')
    done = ['interview', 'requirement_lock_stage', 'spec_compile', 'checklist_critic', 'review_resolution', 'compose_candidate']
    state = {'run_id': 'job', 'plan': {'action': action, 'reason': 'test'}, 'completed_tasks': done,
             'revision': 0, 'document_versions': []}
    result = await flow.execute(state)
    assert result['completed_tasks'] == [item for item in done if item not in invalidated]


@pytest.mark.parametrize(('boundary', 'error_type', 'expected_type'), [
    ('get', 'invalid_state', 'invalid_state'), ('get', 'access', 'access'),
    ('begin', 'invalid_state', 'persistence'), ('begin', 'access', 'access'),
    ('progress', 'invalid_state', 'persistence'), ('progress', 'access', 'access'),
    ('complete', 'invalid_state', 'persistence'), ('complete', 'access', 'persistence'),
])
@run_async
async def test_durable_storage_boundary_exception_contract(boundary, error_type, expected_type):
    from backend.access.context import AccessError
    from backend.errors import InvalidStateError
    types = {'access': AccessError, 'invalid_state': InvalidStateError, 'persistence': WorkflowPersistenceError}
    flow = AgentWorkflow(SimpleNamespace(), None, journal_writer(), EvidenceRegistry())
    flow.journal = SimpleNamespace(get=AsyncMock(), progress=AsyncMock(), failed=AsyncMock(),
                                   begin=AsyncMock(), prepare=AsyncMock(), complete=AsyncMock())
    flow.journal.get.return_value = None
    getattr(flow.journal, boundary).side_effect = types[error_type]('failure')
    from backend.infrastructure.workflow_store import provider_entered
    async def operation(_state):
        if boundary == 'progress':
            await provider_entered()
        return {}
    with pytest.raises(types[expected_type]):
        await flow.durable('checklist_critic', {'run_id': 'job', 'revision': 0, 'plan_history': []}, operation)


@pytest.mark.parametrize(("error_type", "expected_type"), [("invalid_state", "persistence"), ("access", "access")])
@run_async
async def test_state_persistence_boundary_exception_contract(error_type, expected_type):
    from backend.access.context import AccessError
    from backend.errors import InvalidStateError
    types = {"access": AccessError, "invalid_state": InvalidStateError, "persistence": WorkflowPersistenceError}
    writer = Mock(changed={}, state={})
    @asynccontextmanager
    async def transaction():
        yield
    writer.store.transaction = transaction
    writer.write_json = AsyncMock(side_effect=types[error_type]("failure"))
    flow = AgentWorkflow(SimpleNamespace(runtime=SimpleNamespace(meter=None)), None, writer, EvidenceRegistry())
    with pytest.raises(types[expected_type]):
        await flow.persist("state", {"run_id": "job", "user_request": "request"})
