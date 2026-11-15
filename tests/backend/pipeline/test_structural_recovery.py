from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
from contextlib import asynccontextmanager, nullcontext

import pytest
from tests.backend.application.async_helpers import run_async

from backend.application.execution_history import ExecutionHistory
from backend.application.history_detail import HistoryNode
from backend.errors import ReviewValidationError
from backend.pipeline.builder import _stage
from backend.services import rubric
from tests.support.rubric_helpers import case, failed_review


def journal_writer():
    @asynccontextmanager
    async def transaction():
        yield
    return SimpleNamespace(changed={}, state={}, bind_versions=AsyncMock(),
                           stage_writes=lambda: nullcontext(None),
                           restore_stage=lambda _history: None, flush_stage=AsyncMock(),
                           store=SimpleNamespace(transaction=transaction))


@run_async
async def test_stale_prerequisite_does_not_retry_model_correction():
    calls = AsyncMock(side_effect=rubric.invalid('rubric_stale', stage='checklist_critic'))
    events = []
    with pytest.raises(ReviewValidationError):
        (await _stage('checklist_critic', calls, AsyncMock(side_effect=events.append))({}))
    assert calls.call_count == 1
    assert not [e for e in events if e['state'] == 'retrying']
    assert events[-1]['result']['diagnostic']['category'] == 'prerequisite_stale'


@run_async
async def test_failed_review_does_not_claim_review_was_saved():
    history = ExecutionHistory(SimpleNamespace(usage=AsyncMock(return_value={'attempts': []})))
    data = {'nodes': [], 'executions': []}
    history._load = AsyncMock(return_value=data)
    history._save = AsyncMock()
    ex = (await history.start_execution('generate', input_data='request'))
    (await history.stage(ex, 'checklist_critic', 'started'))
    (await history.stage(ex, 'checklist_critic', 'failed', result={'diagnostic': {'error_code': 'REVIEW_VALIDATION_FAILED', 'error_stage': 'checklist_critic', 'failed_checks': ['rubric_evidence']}}))
    assert data['nodes'][-1]['summary'] != '검토 결과를 저장했습니다.'


def test_current_node_result_wins_over_stale_detail():
    node = HistoryNode.parse({'result': {'plan': {'goal': 'current'}}, 'detail': {'result': {'plan': {'goal': 'old'}}}})
    assert node.result['plan']['goal'] == 'current'


def test_server_derives_critical_and_caps_proposed_score(case):
    value = failed_review(case)
    value.critical_failures = []
    value.score = 10
    evaluation = rubric.validate_evaluation(value, case.record, case.spec)
    assert evaluation['critical_failures'] == ['RUB-001']
    assert evaluation['proposed_score'] == 10
    assert evaluation['score'] == 4


def test_recovery_invalidates_evaluation_without_recompiling_draft(case):
    from backend.services.execution_segment import prepare_segment
    state = {**case.state, 'rubric_evaluation': {}, 'completed_tasks': ['requirement_lock_stage', 'spec_compile', 'checklist_critic', 'review_resolution', 'compose_candidate'], 'rubric_recoveries': []}
    recovered = prepare_segment({**state, 'pending_input': {'action': 'rubric_recovery', 'reason': 'evaluation_missing', 'fingerprint': 'fp'}})
    assert recovered['completed_tasks'] == ['requirement_lock_stage', 'spec_compile']
    assert recovered['rubric'] == state['rubric']
    assert recovered['rubric_evaluation'] == {}
    assert len(recovered['rubric_recoveries']) == 1
    with pytest.raises(ReviewValidationError) as error:
        prepare_segment({**state, **recovered, 'pending_input': {'action': 'rubric_recovery', 'reason': 'evaluation_missing', 'fingerprint': 'fp'}})
    assert error.value.validation_reason == 'recovery_exhausted'


def test_recovery_stale_rubric_keeps_current_draft_for_rebuild(case):
    from backend.services.execution_segment import prepare_segment
    state = {**case.state, 'completed_tasks': ['requirement_lock_stage', 'spec_compile', 'checklist_critic'], 'rubric_recoveries': []}
    recovered = prepare_segment({**state, 'pending_input': {'action': 'rubric_recovery', 'reason': 'rubric_input_changed', 'fingerprint': 'fp'}})
    assert recovered['completed_tasks'] == ['requirement_lock_stage']
    assert recovered['rubric_recovery_pending'] is True


@pytest.mark.parametrize(('failed_stage', 'reason'), [('checklist_critic', 'rubric_input_changed'), ('compose_candidate', 'evaluation_missing')])
@run_async
async def test_actual_graph_recovers_stale_without_rewriting_draft(async_store_factory, monkeypatch, failed_stage, reason):
    async with async_store_factory() as store:
        from backend.pipeline.tasks import WorkflowTasks
        from backend.models import RubricResponse, SpecDraftResponse, ReviewResponse
        from tests.support.workflow_helpers import manager_for
        original = getattr(WorkflowTasks, failed_stage)
        attempts = []
        async def fail_once(self, state):
            attempts.append(True)
            if len(attempts) == 1:
                raise rubric.invalid('rubric_stale', stage=failed_stage, reason=reason)
            return (await original(self, state))
        monkeypatch.setattr(WorkflowTasks, failed_stage, fail_once)
        manager, provider = (await manager_for(store, monkeypatch))
        try:
            ident = (await manager.create('메모를 저장해주세요'))['id']
            (await manager._run(ident, 'generate', None))
            job = (await manager.get(ident))
            assert job['status'] == 'PASS_PENDING_USER_APPROVAL', job.get('message')
            assert provider.calls.count(SpecDraftResponse) == 1
            assert provider.calls.count(RubricResponse) == 1
            assert provider.calls.count(ReviewResponse) == (1 if failed_stage == 'checklist_critic' else 2)
            assert len((await manager.workspace.state(ident))['rubric_recoveries']) == 1
        finally:
            (await manager.close())


@run_async
async def test_completed_event_waits_for_stage_commit_and_journal_reuses_result():
    from backend.errors import WorkflowPersistenceError
    from backend.infrastructure.evidence_registry import EvidenceRegistry
    from backend.pipeline.agent_workflow import AgentWorkflow
    from backend.services.rubric import POLICY_VERSION
    events = []
    operation = AsyncMock(return_value={'status': 'ok'})
    staged = _stage('checklist_critic', operation, AsyncMock(side_effect=events.append), defer_completed=True)
    flow = AgentWorkflow(SimpleNamespace(), None, journal_writer(), EvidenceRegistry(), AsyncMock(side_effect=events.append))
    flow.journal = AsyncMock()
    stored = {}
    flow.journal.get.side_effect = lambda *_a, **_kw: {**stored, '_prepared': True} if stored else None
    flow.journal.prepare.side_effect = lambda _id, payload: stored.update(payload)
    flow.persist = AsyncMock(side_effect=[WorkflowPersistenceError('failed'), None])
    state = {'run_id': 'job', 'revision': 1, 'plan_history': []}
    with pytest.raises(WorkflowPersistenceError):
        (await flow.durable('checklist_critic', state, staged))
    assert all(event['state'] != 'completed' for event in events)
    assert flow.journal.complete.call_args.args[1]['rubric_policy_version'] == POLICY_VERSION
    assert (await flow.durable('checklist_critic', state, staged))['status'] == 'ok'
    assert operation.call_count == 1


def test_model_schema_excludes_server_derived_critical_failures():
    from openai.lib._pydantic import to_strict_json_schema
    from backend.models import ReviewResponse
    schema = to_strict_json_schema(ReviewResponse)
    assert 'critical_failures' not in schema['properties']
    assert 'critical_failures' not in schema['required']


@run_async
async def test_actual_graph_stops_after_repeated_identical_recovery_and_retry(async_store_factory, monkeypatch):
    async with async_store_factory() as store:
        from backend.pipeline.tasks import WorkflowTasks
        from tests.support.workflow_helpers import manager_for
        from backend.application.execution_history import ExecutionHistory
        calls = []
        async def fail(self, state):
            calls.append(True)
            raise rubric.invalid('rubric_stale', stage='checklist_critic', reason='rubric_input_changed')
        monkeypatch.setattr(WorkflowTasks, 'checklist_critic', fail)
        manager, provider = (await manager_for(store, monkeypatch))
        try:
            ident = (await manager.create('메모를 저장해주세요'))['id']
            (await manager._run(ident, 'generate', None))
            assert (await manager.get(ident))['status'] == 'error'
            assert len(calls) == 2
            (await manager._run(ident, 'retry', None))
            assert (await manager.get(ident))['status'] == 'error'
            assert len(calls) == 3
            history = ExecutionHistory((await manager.workspace.documents(ident)))
            terminal = (await history.graph())['nodes'][-1]
            assert (await history.detail(terminal['id']))['result']['diagnostic']['validation_reason'] == 'recovery_exhausted'
        finally:
            (await manager.close())


@run_async
async def test_completed_journal_write_failure_reuses_prepared_result():
    from backend.errors import WorkflowPersistenceError
    from backend.infrastructure.evidence_registry import EvidenceRegistry
    from backend.pipeline.agent_workflow import AgentWorkflow
    events = []
    operation = AsyncMock(return_value={'status': 'ok'})
    staged = _stage('checklist_critic', operation, AsyncMock(side_effect=events.append), defer_completed=True)
    flow = AgentWorkflow(SimpleNamespace(), None, journal_writer(), EvidenceRegistry(), AsyncMock(side_effect=events.append))
    flow.journal = AsyncMock()
    stored = {}
    flow.journal.get.side_effect = lambda *_a, **_kw: {**stored, '_prepared': True} if stored else None
    flow.journal.prepare.side_effect = lambda _id, payload: stored.update(payload)
    flow.journal.complete.side_effect = [RuntimeError('storage failed'), None]
    flow.persist = AsyncMock()
    state = {'run_id': 'job', 'revision': 1, 'plan_history': []}
    with pytest.raises(WorkflowPersistenceError):
        (await flow.durable('checklist_critic', state, staged))
    assert (await flow.durable('checklist_critic', state, staged))['status'] == 'ok'
    assert operation.call_count == 1
    assert all(event['state'] != 'completed' for event in events)


def test_current_result_wins_for_captured_issues_and_requirements():
    node = HistoryNode.parse({'result': {'issues': ['current'], 'requirements': ['current']},
                              'detail': {'issues': ['old'], 'requirements': ['old'], 'result': {'issues': ['older']}}})
    assert node.result['issues'] == ['current']
    assert node.result['requirements'] == ['current']


def test_detailed_evidence_diagnostic_keeps_only_verified_references(case):
    from backend.server.diagnostics import diagnose_exception
    value = failed_review(case)
    value.rubric_verdicts[0].evidence_kind = 'quote'
    value.rubric_verdicts[0].quote = 'not present'
    with pytest.raises(ReviewValidationError) as error:
        rubric.validate_evaluation(value, case.record, case.spec)
    diagnostic = diagnose_exception(error.value)
    assert diagnostic['category'] == 'response_invalid'
    assert diagnostic['validation_reason'] == 'quote_not_found'
    assert diagnostic['context']['rubric_id'] == 'RUB-001'
    assert diagnostic['context']['requirement_id'] == 'REQ-001'
    assert 'not present' not in str(diagnostic)


@run_async
async def test_retry_events_do_not_publish_frames_or_raw_exception():
    events = []
    attempts = []
    async def operation(_state):
        attempts.append(True)
        if len(attempts) == 1:
            raise rubric.invalid('rubric_evidence', stage='checklist_critic', reason='quote_not_found')
        return {'status': 'ok'}
    (await _stage('checklist_critic', operation, AsyncMock(side_effect=events.append))({}))
    diagnostic = next(e['result']['diagnostic'] for e in events if e['state'] == 'retrying')
    assert diagnostic['validation_reason'] == 'quote_not_found'
    assert 'frames' not in diagnostic and 'cause_types' not in diagnostic


@pytest.mark.parametrize('failure', ['journal', 'persist'])
@run_async
async def test_graph_durable_failure_requires_safe_resume(async_store_factory, monkeypatch, failure):
    async with async_store_factory() as store:
        from backend.infrastructure.workflow_store import TaskJournal
        from backend.pipeline.agent_workflow import AgentWorkflow
        from backend.models import ReviewResponse
        from tests.support.workflow_helpers import manager_for
        original_complete = TaskJournal.complete
        original_persist = AgentWorkflow.persist
        failed = []
        async def complete(self, ident, payload):
            if failure == 'journal' and not failed and payload.get('result', {}).get('rubric_evaluation'):
                failed.append(True)
                raise RuntimeError('simulated journal failure')
            return (await original_complete(self, ident, payload))
        async def persist(self, stage, state):
            if failure == 'persist' and not failed and stage == 'checklist_critic':
                failed.append(True)
                from backend.errors import WorkflowPersistenceError
                raise WorkflowPersistenceError('simulated persist failure')
            return (await original_persist(self, stage, state))
        monkeypatch.setattr(TaskJournal, 'complete', complete)
        monkeypatch.setattr(AgentWorkflow, 'persist', persist)
        manager, provider = (await manager_for(store, monkeypatch))
        try:
            ident = (await manager.create('메모를 저장해주세요'))['id']
            (await manager._run(ident, 'generate', None))
            job = (await manager.get(ident))
            assert job['status'] == 'error'
            assert provider.calls.count(ReviewResponse) == 1
            from backend.infrastructure.workflow_store import retry_state
            assert (await retry_state((await manager.workspace.documents(ident))))['retry_requires_replay'] is False
            (await manager._run(ident, 'retry', None))
            assert provider.calls.count(ReviewResponse) == 1
            assert (await manager.get(ident))['status'] == 'PASS_PENDING_USER_APPROVAL'
        finally:
            (await manager.close())


@run_async
async def test_deterministic_defect_derived_values_survive_approval_revalidation(case):
    from backend.services.checklist_critic import ChecklistCritic
    from tests.support.rubric_helpers import review
    broken = case.spec.replace('## 1. 목표', '## 목표 누락')
    evaluations = []
    issues = (await ChecklistCritic().critique(broken, case.sheet, rubric=case.record,
        provider_messages_fn=AsyncMock(return_value=review(case)), evaluation_sink=evaluations.append))
    assert issues and evaluations[0]['score'] <= 7
    assert evaluations[0]['critical_failures']
    rubric.require_approval_evaluation({**case.state, 'rubric_evaluation': evaluations[0]}, case.sheet, broken)


@pytest.mark.parametrize('operation', ['get', 'begin', 'progress'])
@run_async
async def test_journal_io_failures_are_classified_as_persistence(operation):
    from backend.errors import WorkflowPersistenceError
    from backend.infrastructure.evidence_registry import EvidenceRegistry
    from backend.pipeline.agent_workflow import AgentWorkflow
    from backend.server.diagnostics import diagnose_exception
    flow = AgentWorkflow(SimpleNamespace(), None, journal_writer(), EvidenceRegistry())
    flow.journal = AsyncMock()
    flow.journal.get.return_value = None
    if operation in {'get', 'begin'}:
        getattr(flow.journal, operation).side_effect = OSError('storage')
        node = AsyncMock(return_value={})
    else:
        from backend.infrastructure.workflow_store import provider_entered
        flow.journal.progress.side_effect = OSError('storage')
        node = lambda _state: provider_entered()
    with pytest.raises(WorkflowPersistenceError) as error:
        (await flow.durable('checklist_critic', {'run_id': 'job', 'revision': 0, 'plan_history': []}, node))
    assert diagnose_exception(error.value)['category'] == 'persistence_failed'


@run_async
async def test_recovery_ledger_survives_checkpoint_write_failure(case):
    from backend.errors import WorkflowPersistenceError
    from backend.infrastructure.evidence_registry import EvidenceRegistry
    from backend.pipeline.agent_workflow import AgentWorkflow
    docs = case.docs
    docs.read_text = AsyncMock(return_value=case.spec)
    flow = AgentWorkflow(SimpleNamespace(), None, docs, EvidenceRegistry())
    flow.persist = AsyncMock()
    graph = AsyncMock()
    graph.aupdate_state.side_effect = OSError('checkpoint storage failure')
    state = {**case.state, 'run_id': 'job', 'completed_tasks': ['requirement_lock_stage', 'spec_compile'], 'rubric_recoveries': []}
    with pytest.raises(WorkflowPersistenceError):
        (await flow.recover_rubric(graph, {}, state, 'rubric_input_changed'))
    with pytest.raises(ReviewValidationError) as error:
        (await flow.recover_rubric(graph, {}, state, 'rubric_input_changed'))
    assert error.value.validation_reason == 'recovery_exhausted'
    assert graph.aupdate_state.call_count == 1


@run_async
async def test_recovery_ledger_is_recorded_before_input_persist_failure(case):
    from backend.errors import WorkflowPersistenceError
    from backend.infrastructure.evidence_registry import EvidenceRegistry
    from backend.pipeline.agent_workflow import AgentWorkflow
    docs = case.docs
    docs.read_text = AsyncMock(return_value=case.spec)
    flow = AgentWorkflow(SimpleNamespace(), None, docs, EvidenceRegistry())
    flow.persist = AsyncMock(side_effect=WorkflowPersistenceError('simulated'))
    graph = AsyncMock()
    state = {**case.state, 'run_id': 'job', 'completed_tasks': ['requirement_lock_stage', 'spec_compile'], 'rubric_recoveries': []}
    with pytest.raises(WorkflowPersistenceError):
        (await flow.recover_rubric(graph, {}, state, 'rubric_input_changed'))
    assert (await docs.exists('state/rubric_recoveries.json'))
    with pytest.raises(ReviewValidationError) as error:
        (await flow.recover_rubric(graph, {}, state, 'rubric_input_changed'))
    assert error.value.validation_reason == 'recovery_exhausted'
    graph.aupdate_state.assert_not_called()


@run_async
async def test_terminal_persistence_failure_keeps_actual_failed_stage():
    history = ExecutionHistory(SimpleNamespace(usage=AsyncMock(return_value={'attempts': []})))
    data = {'nodes': [], 'executions': []}
    history._load = AsyncMock(return_value=data)
    history._save = AsyncMock()
    execution = (await history.start_execution('generate', input_data='request'))
    (await history.stage(execution, 'checklist_critic', 'started'))
    (await history.terminal(execution, 'error', 'save failed', result={'diagnostic': {
        'error_code': 'WORKFLOW_PERSISTENCE_FAILED', 'error_stage': None,
        'category': 'persistence_failed', 'failed_checks': []}}))
    diagnostic = (await history.detail(data['nodes'][-1]['id']))['result']['diagnostic']
    assert diagnostic['error_stage'] == 'checklist_critic'
    assert diagnostic['category'] == 'persistence_failed'
