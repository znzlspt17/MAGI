"""워크플로 완료 경로와 비동기 RAG 큐의 내구성 및 격리 검증."""

import asyncio
import sys
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.knowledge.runtime import KnowledgeService, RunKnowledge
from backend.pipeline.agent_workflow import AgentWorkflow


def run(coroutine):
    factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=factory) as runner:
        return runner.run(coroutine)


class QueueStore:
    def __init__(self):
        self.items = []
        self.fail = False

    async def action_records(self, _job_id):
        return []

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def enqueue_stage(self, job, execution, stage, state, artifacts, *, connection):
        assert connection is self
        if self.fail:
            raise RuntimeError("queue write failed")
        self.items.append(deepcopy((job, execution, stage, state, artifacts)))

    async def commit_stage(self, *_args, **_kwargs):
        raise AssertionError("projection was computed on the request path")


def test_commit_durably_enqueues_immutable_input_without_projecting():
    async def scenario():
        store = QueueStore()
        scheduled = []
        documents = SimpleNamespace(state={}, all=AsyncMock(return_value={"spec": "v1"}))
        runtime = RunKnowledge(SimpleNamespace(store=store, schedule=lambda: scheduled.append(True)),
                               {"id": "job", "execution_id": "run"}, documents)
        state = {"requirements": ["first"]}
        await runtime.commit("spec_compile", state)
        state["requirements"].append("later")
        assert store.items == [({"id": "job", "execution_id": "run"}, "run", "spec_compile",
                                {"requirements": ["first"]}, {"spec": "v1"})]
        assert scheduled == [True]
    run(scenario())


def test_failed_enqueue_does_not_signal_success_or_schedule():
    async def scenario():
        store = QueueStore()
        store.fail = True
        scheduled = []
        documents = SimpleNamespace(state={}, all=AsyncMock(return_value={}))
        runtime = RunKnowledge(SimpleNamespace(store=store, schedule=lambda: scheduled.append(True)),
                               {"id": "job", "execution_id": "run"}, documents)
        with pytest.raises(RuntimeError, match="queue write failed"):
            await runtime.commit("spec_compile", {})
        assert scheduled == []
    run(scenario())


def test_projection_queue_applies_saved_snapshots_in_job_order(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project("queue")
            job = {"id": "rag-queue-job", "project_id": project["id"], "request": "input"}
            await store.save_job(job)
            async with store.transaction() as conn:
                await store.enqueue_stage(job, "run", "requirement_lock", {"user_request": "first"}, {}, connection=conn)
                await store.enqueue_stage(job, "run", "requirement_lock", {"user_request": "second"}, {}, connection=conn)
            assert (await store.projection_status(job["id"]))["index_status"] == "pending"
            assert (await store.projection_status(project_id=project["id"]))["index_status"] == "pending"
            assert await store.process_projection() is True
            async with store.transaction(mode="read") as conn:
                assert (await (await conn.execute("SELECT body FROM nodes WHERE job_id=%s AND active", (job["id"],))).fetchone())["body"] == "first"
            assert await store.process_projection() is True
            async with store.transaction(mode="read") as conn:
                assert (await (await conn.execute("SELECT body FROM nodes WHERE job_id=%s AND active", (job["id"],))).fetchone())["body"] == "second"
            status = await store.projection_status(job["id"])
            assert status["index_status"] == "ready"
            assert status["index_source_revision"] == status["index_applied_revision"]
    run(scenario())


def test_graph_reports_index_status_for_its_requested_project(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('graph status')
            job = {'id': 'graph-job', 'project_id': project['id'], 'request': 'input'}
            await store.save_job(job)
            async with store.transaction() as conn:
                await store.enqueue_stage(job, 'run', 'requirement_lock', {'user_request': 'input'}, {}, connection=conn)
            graph = await store.graph(project_id=project['id'])
            assert graph['index_status'] == 'pending'
            assert graph['index_source_revision'] > graph['index_applied_revision']
    run(scenario())


def test_queue_transition_emits_job_progress_with_index_status(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('queue events')
            job = {'id': 'event-job', 'project_id': project['id'], 'execution_id': 'run', 'request': 'input'}
            await store.save_job(job)
            async with store.transaction() as conn:
                await store.enqueue_stage(job, 'run', 'requirement_lock', {'user_request': 'input'}, {}, connection=conn)
            async with store.transaction(mode='read') as conn:
                event = await (await conn.execute('SELECT payload FROM progress_outbox WHERE job_id=%s ORDER BY id DESC LIMIT 1', (job['id'],))).fetchone()
            assert event['payload']['job']['index_status'] == 'pending'
            assert event['payload']['job']['index_source_revision'] > event['payload']['job']['index_applied_revision']
    run(scenario())


def test_public_service_schedules_projection_and_embedding_independently():
    async def scenario():
        projected = asyncio.Event()
        class Store:
            config = SimpleNamespace(model_path=None, device="cpu")
            async def process_projection(self):
                if not projected.is_set():
                    projected.set()
                    return True
                return False
        class Embedder:
            def info(self):
                raise RuntimeError("not available")
            def close(self):
                pass
        service = KnowledgeService(Store(), embedder=Embedder())
        service.public_mode = True
        try:
            service.schedule()
            await asyncio.wait_for(projected.wait(), timeout=1)
        finally:
            await service.close()
    run(scenario())


def test_stage_source_and_queue_commit_share_a_transaction(monkeypatch):
    async def scenario():
        class Store:
            active = False
            @asynccontextmanager
            async def transaction(self):
                self.active = True
                try:
                    yield self
                finally:
                    self.active = False
        store = Store()
        class Writer:
            def __init__(self):
                self.store = store
            async def write_json(self, *_args):
                assert store.active, "stage source must be persisted inside the queue transaction"
        class Runtime:
            meter = None
            async def commit(self, stage, state):
                assert store.active
                assert stage == "spec_compile" and state == {"version": 1}
        monkeypatch.setattr("backend.pipeline.agent_workflow.State.from_dict",
                            lambda value: SimpleNamespace(to_dict=lambda: value))
        workflow = AgentWorkflow(SimpleNamespace(runtime=Runtime()), None, Writer(),
                                 SimpleNamespace(to_dict=lambda: {}))
        await workflow.persist("spec_compile", {"version": 1})
    run(scenario())


@pytest.mark.parametrize('failure_kind', ['enqueue', 'commit'])
def test_direct_persist_restores_writer_metadata_when_transaction_fails(async_store_factory, monkeypatch, failure_kind):
    from backend.knowledge.core import Documents
    from backend.infrastructure.evidence_registry import EvidenceRegistry
    from backend.errors import ArtifactError, WorkflowPersistenceError
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('persist rollback')
            job = {'id': 'persist-rollback', 'project_id': project['id'], 'execution_id': 'run', 'request': 'input'}
            await store.save_job(job)
            writer = Documents(store, job['id'])
            writer.state = {'before': True}
            runtime = RunKnowledge(SimpleNamespace(store=store, schedule=lambda: None), job, writer)
            flow = AgentWorkflow(SimpleNamespace(runtime=runtime), None, writer, EvidenceRegistry())
            monkeypatch.setattr('backend.pipeline.agent_workflow.State.from_dict', lambda value: SimpleNamespace(to_dict=lambda: value))
            original_enqueue = store.enqueue_stage
            async def fail(*args, **kwargs):
                if failure_kind == 'enqueue':
                    raise RuntimeError('queue unavailable')
                result = await original_enqueue(*args, **kwargs)
                conn = kwargs['connection']
                await conn.execute('CREATE TEMP TABLE persist_commit_failure (job_id text REFERENCES core.jobs(id) DEFERRABLE INITIALLY DEFERRED) ON COMMIT DROP')
                await conn.execute("INSERT INTO persist_commit_failure VALUES ('missing-job')")
                return result
            monkeypatch.setattr(store, 'enqueue_stage', fail)
            with pytest.raises(WorkflowPersistenceError):
                await flow.persist('spec_compile', {'new': True})
            assert writer.state == {'before': True} and writer.changed == {}
            with pytest.raises(ArtifactError):
                await writer.read_text('evidence/evidence_registry.json')
    run(scenario())


@pytest.mark.parametrize('stage_name', ['spec_compile', 'requirement_lock_stage', 'compose_candidate'])
def test_durable_stage_rolls_back_documents_and_journal_when_enqueue_fails(async_store_factory, monkeypatch, stage_name):
    from backend.infrastructure.workflow_store import TaskJournal
    from backend.knowledge.core import Documents
    from backend.knowledge.store import ASYNC_TRANSACTION
    from backend.errors import ArtifactError, WorkflowPersistenceError

    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('atomic')
            job = {'id': 'atomic-job', 'project_id': project['id'], 'execution_id': 'run', 'request': 'input'}
            await store.save_job(job)
            writer = Documents(store, job['id'])
            runtime = RunKnowledge(SimpleNamespace(store=store, schedule=lambda: None), job, writer)
            workflow = AgentWorkflow(SimpleNamespace(runtime=runtime), None, writer, SimpleNamespace(to_dict=lambda: {}))
            workflow.journal = TaskJournal(store, job['id'])
            monkeypatch.setattr('backend.pipeline.agent_workflow.State.from_dict', lambda value: SimpleNamespace(to_dict=lambda: value))
            async def operation(_state):
                await writer.write_text('draft/approval_candidate_spec.ko.md', 'new document')
                assert await writer.read_text('draft/approval_candidate_spec.ko.md') == 'new document'
                assert ASYNC_TRANSACTION.get() is None
                # 별도 태스크는 미확정 산출물을 볼 수 없다.
                async def observe():
                    with pytest.raises(ArtifactError):
                        await store.documents(job['id']).read_text('draft/approval_candidate_spec.ko.md')
                await asyncio.create_task(observe())
                return {'status': 'done'}
            original_enqueue = store.enqueue_stage
            async def fail_enqueue(*_args, **_kwargs):
                raise RuntimeError('queue unavailable')
            monkeypatch.setattr(store, 'enqueue_stage', fail_enqueue)
            with pytest.raises(WorkflowPersistenceError):
                await workflow.durable(stage_name, {'run_id': 'run'}, operation)
            with pytest.raises(ArtifactError):
                await writer.read_text('draft/approval_candidate_spec.ko.md')
            async with store.transaction(mode='read') as conn:
                journal = await (await conn.execute('SELECT status FROM workflow.workflow_task_results WHERE thread_id=%s', (job['id'],))).fetchone()
                queued = await (await conn.execute('SELECT count(*) AS total FROM projection_queue')).fetchone()
            assert journal['status'] == 'prepared' and queued['total'] == 0
            monkeypatch.setattr(store, 'enqueue_stage', original_enqueue)
    run(scenario())


def test_durable_stage_commit_failure_rolls_back_queue_journal_and_documents(async_store_factory, monkeypatch):
    from backend.infrastructure.workflow_store import TaskJournal
    from backend.knowledge.core import Documents
    from backend.errors import ArtifactError, WorkflowPersistenceError
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('commit failure')
            job = {'id': 'commit-failure', 'project_id': project['id'], 'execution_id': 'run', 'request': 'input'}
            await store.save_job(job)
            writer = Documents(store, job['id'])
            runtime = RunKnowledge(SimpleNamespace(store=store, schedule=lambda: None), job, writer)
            workflow = AgentWorkflow(SimpleNamespace(runtime=runtime), None, writer, SimpleNamespace(to_dict=lambda: {}))
            workflow.journal = TaskJournal(store, job['id'])
            monkeypatch.setattr('backend.pipeline.agent_workflow.State.from_dict', lambda value: SimpleNamespace(to_dict=lambda: value))
            original_enqueue = store.enqueue_stage
            async def invalid_commit(*args, **kwargs):
                value = await original_enqueue(*args, **kwargs)
                conn = kwargs['connection']
                await conn.execute('CREATE TEMP TABLE commit_failure_fixture (job_id text REFERENCES core.jobs(id) DEFERRABLE INITIALLY DEFERRED) ON COMMIT DROP')
                await conn.execute("INSERT INTO commit_failure_fixture VALUES ('missing-job')")
                return value
            monkeypatch.setattr(store, 'enqueue_stage', invalid_commit)
            async def operation(_state):
                await writer.write_text('draft/approval_candidate_spec.ko.md', 'not committed')
                return {'status': 'done'}
            with pytest.raises(WorkflowPersistenceError):
                await workflow.durable('spec_compile', {'run_id': 'run'}, operation)
            with pytest.raises(ArtifactError):
                await writer.read_text('draft/approval_candidate_spec.ko.md')
            assert writer.changed == {} and writer.state == {}
            async with store.transaction(mode='read') as conn:
                journal = await (await conn.execute('SELECT status FROM workflow.workflow_task_results WHERE thread_id=%s', (job['id'],))).fetchone()
                count = await (await conn.execute('SELECT count(*) AS total FROM projection_queue')).fetchone()
            assert journal['status'] == 'prepared' and count['total'] == 0
    run(scenario())


def test_durable_stage_commit_and_replay_use_the_same_document_versions(async_store_factory, monkeypatch):
    from backend.infrastructure.workflow_store import TaskJournal
    from backend.knowledge.core import Documents
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('atomic success')
            job = {'id': 'atomic-success', 'project_id': project['id'], 'execution_id': 'run', 'request': 'input'}
            await store.save_job(job)
            writer = Documents(store, job['id'])
            runtime = RunKnowledge(SimpleNamespace(store=store, schedule=lambda: None), job, writer)
            workflow = AgentWorkflow(SimpleNamespace(runtime=runtime), None, writer, SimpleNamespace(to_dict=lambda: {}))
            workflow.journal = TaskJournal(store, job['id'])
            monkeypatch.setattr('backend.pipeline.agent_workflow.State.from_dict', lambda value: SimpleNamespace(to_dict=lambda: value))
            version = None
            async def operation(_state):
                nonlocal version
                scoped = writer.scope('draft')
                await scoped.write_text('approval_candidate_spec.ko.md', 'new document')
                version = await scoped.reference('approval_candidate_spec.ko.md')
                assert await writer.version(version) == 'new document'
                assert (await writer.all())['draft/approval_candidate_spec.ko.md'] == 'new document'
                return {'status': 'done'}
            state = {'run_id': 'run'}
            await workflow.durable('spec_compile', state, operation)
            assert await writer.version(version) == 'new document'
            async with store.transaction(mode='read') as conn:
                queue = await (await conn.execute('SELECT artifacts FROM projection_queue')).fetchone()
            assert queue['artifacts']['draft/approval_candidate_spec.ko.md'] == 'new document'
            await workflow.durable('spec_compile', state, lambda _: pytest.fail('completed stage called again'))
            assert await writer.read_text('draft/approval_candidate_spec.ko.md') == 'new document'
    run(scenario())


def test_replay_rolls_back_rebound_document_when_enqueue_fails(async_store_factory, monkeypatch):
    from backend.infrastructure.workflow_store import TaskJournal
    from backend.knowledge.core import Documents
    from backend.errors import WorkflowPersistenceError
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('atomic replay')
            job = {'id': 'atomic-replay', 'project_id': project['id'], 'execution_id': 'run', 'request': 'input'}
            await store.save_job(job)
            writer = Documents(store, job['id'])
            runtime = RunKnowledge(SimpleNamespace(store=store, schedule=lambda: None), job, writer)
            workflow = AgentWorkflow(SimpleNamespace(runtime=runtime), None, writer, SimpleNamespace(to_dict=lambda: {}))
            workflow.journal = TaskJournal(store, job['id'])
            monkeypatch.setattr('backend.pipeline.agent_workflow.State.from_dict', lambda value: SimpleNamespace(to_dict=lambda: value))
            async def operation(_state):
                await writer.write_text('draft/approval_candidate_spec.ko.md', 'saved result')
                return {'status': 'done'}
            state = {'run_id': 'run'}
            await workflow.durable('spec_compile', state, operation)
            await writer.write_text('draft/approval_candidate_spec.ko.md', 'newer document')
            async def fail_enqueue(*_args, **_kwargs):
                raise RuntimeError('queue unavailable')
            monkeypatch.setattr(store, 'enqueue_stage', fail_enqueue)
            with pytest.raises(WorkflowPersistenceError):
                await workflow.durable('spec_compile', state, operation)
            assert await writer.read_text('draft/approval_candidate_spec.ko.md') == 'newer document'
    run(scenario())


def test_prepared_stage_recovers_after_restart_without_calling_model_again(async_store_factory, monkeypatch):
    from backend.infrastructure.workflow_store import TaskJournal
    from backend.infrastructure.evidence_registry import EvidenceRegistry
    from backend.knowledge.core import Documents
    from backend.errors import ArtifactError, WorkflowPersistenceError
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('prepared replay')
            job = {'id': 'prepared-replay', 'project_id': project['id'], 'execution_id': 'run', 'request': 'input'}
            await store.save_job(job)
            def make_flow():
                writer = Documents(store, job['id'])
                runtime = RunKnowledge(SimpleNamespace(store=store, schedule=lambda: None), job, writer)
                flow = AgentWorkflow(SimpleNamespace(runtime=runtime), None, writer, EvidenceRegistry())
                flow.journal = TaskJournal(store, job['id'])
                return flow
            monkeypatch.setattr('backend.pipeline.agent_workflow.State.from_dict', lambda value: SimpleNamespace(to_dict=lambda: value))
            first = make_flow()
            references = []
            calls = []
            async def operation(_state):
                calls.append(True)
                for content in ('first', 'second'):
                    await first.writer.write_text('draft/approval_candidate_spec.ko.md', content)
                    references.append(await first.writer.reference('draft/approval_candidate_spec.ko.md'))
                return {'status': 'done'}
            original_enqueue = store.enqueue_stage
            async def fail_enqueue(*_args, **_kwargs):
                raise RuntimeError('queue unavailable')
            monkeypatch.setattr(store, 'enqueue_stage', fail_enqueue)
            state = {'run_id': 'run'}
            with pytest.raises(WorkflowPersistenceError):
                await first.durable('spec_compile', state, operation)
            with pytest.raises(ArtifactError):
                await first.writer.read_text('draft/approval_candidate_spec.ko.md')
            monkeypatch.setattr(store, 'enqueue_stage', original_enqueue)
            resumed = make_flow()
            assert (await resumed.durable('spec_compile', state, operation))['status'] == 'done'
            assert calls == [True]
            assert [await resumed.writer.version(ident) for ident in references] == ['first', 'second']
            await resumed.durable('spec_compile', state, operation)
            async with store.transaction(mode='read') as conn:
                count = await (await conn.execute('SELECT count(*) AS total FROM projection_queue')).fetchone()
            assert count['total'] == 1 and calls == [True]
    run(scenario())


def test_failed_prepared_receipt_keeps_uncertain_journal_pending(async_store_factory, monkeypatch):
    from backend.infrastructure.workflow_store import TaskJournal, provider_entered
    from backend.infrastructure.evidence_registry import EvidenceRegistry
    from backend.knowledge.core import Documents
    from backend.errors import ArtifactError, InvalidStateError, WorkflowPersistenceError
    from backend.pipeline.agent_workflow import task_id
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('prepared failure')
            job = {'id': 'prepared-failure', 'project_id': project['id'], 'execution_id': 'run', 'request': 'input'}
            await store.save_job(job)
            writer = Documents(store, job['id'])
            runtime = RunKnowledge(SimpleNamespace(store=store, schedule=lambda: None), job, writer)
            flow = AgentWorkflow(SimpleNamespace(runtime=runtime), None, writer, EvidenceRegistry())
            flow.journal = TaskJournal(store, job['id'])
            async def fail_prepare(*_args, **_kwargs):
                raise RuntimeError('receipt unavailable')
            monkeypatch.setattr(flow.journal, 'prepare', fail_prepare)
            async def operation(_state):
                await provider_entered()
                await writer.write_text('draft/approval_candidate_spec.ko.md', 'private')
                return {'status': 'done'}
            state = {'run_id': 'run'}
            with pytest.raises(WorkflowPersistenceError):
                await flow.durable('spec_compile', state, operation)
            assert await flow.journal.status(task_id(state, 'spec_compile')) == 'pending'
            with pytest.raises(InvalidStateError):
                await flow.journal.get(task_id(state, 'spec_compile'))
            with pytest.raises(ArtifactError):
                await writer.read_text('draft/approval_candidate_spec.ko.md')
    run(scenario())


def test_execute_requirement_lock_rolls_back_source_when_queue_fails(async_store_factory, monkeypatch):
    from backend.infrastructure.workflow_store import TaskJournal
    from backend.knowledge.core import Documents
    from backend.errors import ArtifactError, WorkflowPersistenceError
    import backend.pipeline.agent_workflow as workflow_module
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('execute atomic')
            job = {'id': 'execute-atomic', 'project_id': project['id'], 'execution_id': 'run', 'request': 'input'}
            await store.save_job(job)
            writer = Documents(store, job['id'])
            runtime = RunKnowledge(SimpleNamespace(store=store, schedule=lambda: None), job, writer)
            async def lock(_state):
                await writer.write_text('analysis/requirement_lock_sheet.json', 'source')
                return {'requirement_lock_sheet': {}}
            workflow = AgentWorkflow(SimpleNamespace(runtime=runtime, config=None), SimpleNamespace(requirement_lock_stage=lock),
                                     writer, SimpleNamespace(to_dict=lambda: {}))
            workflow.journal = TaskJournal(store, job['id'])
            monkeypatch.setattr(workflow_module, 'execution_constraints', lambda *_: {'repeated_actions': []})
            monkeypatch.setattr(workflow_module, 'evaluate_execution', lambda *_: SimpleNamespace(allowed_actions={'requirement_lock_stage'}))
            monkeypatch.setattr(workflow_module, 'task_signature', lambda *_: 'signature')
            monkeypatch.setattr(workflow_module.State, 'from_dict', lambda value: SimpleNamespace(to_dict=lambda: value))
            async def reject(*_args, **_kwargs):
                raise RuntimeError('queue unavailable')
            monkeypatch.setattr(store, 'enqueue_stage', reject)
            state = {'run_id': 'run', 'plan': {'action': 'requirement_lock_stage', 'reason': 'test'}, 'revision': 0}
            with pytest.raises(WorkflowPersistenceError):
                await workflow.execute(state)
            with pytest.raises(ArtifactError):
                await writer.read_text('analysis/requirement_lock_sheet.json')
            async with store.transaction(mode='read') as conn:
                queued = await (await conn.execute('SELECT count(*) AS total FROM projection_queue')).fetchone()
                journal = await (await conn.execute('SELECT status FROM workflow.workflow_task_results WHERE thread_id=%s', (job['id'],))).fetchone()
            assert queued['total'] == 0 and journal['status'] == 'prepared'
    run(scenario())


def test_execute_review_failure_does_not_publish_restored_draft(async_store_factory, monkeypatch):
    import hashlib
    import backend.pipeline.agent_workflow as workflow_module
    from backend.infrastructure.workflow_store import TaskJournal
    from backend.infrastructure.evidence_registry import EvidenceRegistry
    from backend.knowledge.core import Documents
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('review restore')
            job = {'id': 'review-restore', 'project_id': project['id'], 'execution_id': 'run', 'request': 'input'}
            await store.save_job(job)
            writer = Documents(store, job['id'])
            version_hash = hashlib.sha256(b'older reviewed draft').hexdigest()
            await writer.write_text('draft/approval_candidate_spec.ko.md', 'current draft')
            await writer.write_text(f'draft_versions/{version_hash}.md', 'older reviewed draft')
            runtime = RunKnowledge(SimpleNamespace(store=store, schedule=lambda: None), job, writer)
            async def fail(_state):
                assert await writer.read_text('draft/approval_candidate_spec.ko.md') == 'older reviewed draft'
                raise RuntimeError('review failed')
            flow = AgentWorkflow(SimpleNamespace(runtime=runtime, config=None), SimpleNamespace(checklist_critic=fail), writer, EvidenceRegistry())
            flow.journal = TaskJournal(store, job['id'])
            monkeypatch.setattr(workflow_module, 'execution_constraints', lambda *_: {'repeated_actions': []})
            monkeypatch.setattr(workflow_module, 'evaluate_execution', lambda *_: SimpleNamespace(allowed_actions={'checklist_critic'}))
            monkeypatch.setattr(workflow_module, 'task_signature', lambda *_: 'signature')
            state = {'run_id': 'run', 'plan': {'action': 'checklist_critic', 'reason': 'test'},
                     'revision': 0, 'document_versions': [{'hash': version_hash}]}
            with pytest.raises(RuntimeError, match='review failed'):
                await flow.execute(state)
            assert await writer.read_text('draft/approval_candidate_spec.ko.md') == 'current draft'
    run(scenario())


def test_ask_review_rolls_back_document_if_queue_fails(async_store_factory, monkeypatch):
    import backend.pipeline.agent_workflow as workflow_module
    from backend.infrastructure.workflow_store import TaskJournal
    from backend.infrastructure.evidence_registry import EvidenceRegistry
    from backend.knowledge.core import Documents
    from backend.errors import ArtifactError, WorkflowPersistenceError
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('ask review atomic')
            job = {'id': 'ask-atomic', 'project_id': project['id'], 'execution_id': 'run', 'request': 'input'}
            await store.save_job(job)
            writer = Documents(store, job['id'])
            runtime = RunKnowledge(SimpleNamespace(store=store, schedule=lambda: None), job, writer)
            async def review(_state, *, final):
                assert final
                await writer.write_text('review/resolution.json', 'review')
                return {'blocking_questions': ['question']}
            flow = AgentWorkflow(SimpleNamespace(runtime=runtime, config=None), SimpleNamespace(review_resolution=review, await_user=lambda _state: {}), writer, EvidenceRegistry())
            flow.journal = TaskJournal(store, job['id'])
            monkeypatch.setattr(workflow_module, 'execution_constraints', lambda *_: {'repeated_actions': []})
            monkeypatch.setattr(workflow_module, 'task_signature', lambda *_: 'signature')
            monkeypatch.setattr(workflow_module.State, 'from_dict', lambda value: SimpleNamespace(to_dict=lambda: value))
            async def reject(*_args, **_kwargs):
                raise RuntimeError('queue unavailable')
            monkeypatch.setattr(store, 'enqueue_stage', reject)
            state = {'run_id': 'run', 'requirement_lock_sheet': {'required': True},
                     'structured_issues': [{'status': 'open', 'severity': 'major'}]}
            with pytest.raises(WorkflowPersistenceError):
                await flow.ask(state)
            with pytest.raises(ArtifactError):
                await writer.read_text('review/resolution.json')
    run(scenario())


@pytest.mark.parametrize('failure_kind', ['enqueue', 'commit'])
def test_rubric_recovery_restored_draft_requires_queue_commit(async_store_factory, monkeypatch, failure_kind):
    import hashlib
    import backend.pipeline.agent_workflow as workflow_module
    from backend.infrastructure.evidence_registry import EvidenceRegistry
    from backend.knowledge.core import Documents
    from backend.errors import WorkflowPersistenceError
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('recovery atomic')
            job = {'id': 'recovery-atomic', 'project_id': project['id'], 'execution_id': 'run', 'request': 'input'}
            await store.save_job(job)
            writer = Documents(store, job['id'])
            previous = 'previous draft'
            version_hash = hashlib.sha256(previous.encode()).hexdigest()
            await writer.write_text('draft/approval_candidate_spec.ko.md', 'current draft')
            await writer.write_text(f'draft_versions/{version_hash}.md', previous)
            current_version = await writer.reference('draft/approval_candidate_spec.ko.md')
            runtime = RunKnowledge(SimpleNamespace(store=store, schedule=lambda: None), job, writer)
            flow = AgentWorkflow(SimpleNamespace(runtime=runtime), None, writer, EvidenceRegistry())
            monkeypatch.setattr(workflow_module.State, 'from_dict', lambda value: SimpleNamespace(to_dict=lambda: value))
            monkeypatch.setattr('backend.models.RequirementLockSheet.from_dict', lambda _value: SimpleNamespace(require_validated=lambda: None))
            monkeypatch.setattr('backend.services.rubric.inputs', lambda *_: (None, 'input-hash'))
            monkeypatch.setattr('backend.services.execution_segment.prepare_segment', lambda _state: {'rubric_recoveries': ['new']})
            original_enqueue = store.enqueue_stage
            async def reject(*args, **kwargs):
                if args[2] == 'spec_compile':
                    if failure_kind == 'enqueue':
                        raise RuntimeError('queue unavailable')
                    result = await original_enqueue(*args, **kwargs)
                    conn = kwargs['connection']
                    await conn.execute('CREATE TEMP TABLE recovery_commit_failure (job_id text REFERENCES core.jobs(id) DEFERRABLE INITIALLY DEFERRED) ON COMMIT DROP')
                    await conn.execute("INSERT INTO recovery_commit_failure VALUES ('missing-job')")
                    return result
                return await original_enqueue(*args, **kwargs)
            monkeypatch.setattr(store, 'enqueue_stage', reject)
            graph = SimpleNamespace(aupdate_state=AsyncMock())
            state = {'run_id': 'run', 'requirement_lock_sheet': {}, 'document_versions': [{'hash': version_hash}]}
            with pytest.raises(WorkflowPersistenceError):
                await flow.recover_rubric(graph, {}, state, 'evaluation_missing')
            assert await writer.read_text('draft/approval_candidate_spec.ko.md') == 'current draft'
            assert writer.changed['draft/approval_candidate_spec.ko.md'] == current_version
            assert await writer.exists('state/rubric_recoveries.json')
            graph.aupdate_state.assert_not_called()
    run(scenario())


@pytest.mark.parametrize('fail_queue', [True, False])
def test_partial_answer_and_input_queue_commit_together(async_store_factory, monkeypatch, fail_queue):
    from backend.engine import Engine
    from backend.knowledge.core import Documents
    from backend.models import State
    from backend.errors import ArtifactError
    from backend.knowledge.config import KnowledgeError
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('answer atomic')
            job = {'id': 'answer-atomic', 'project_id': project['id'], 'execution_id': 'run', 'request': 'input'}
            await store.save_job(job)
            writer = Documents(store, job['id'])
            runtime = RunKnowledge(SimpleNamespace(store=store, schedule=lambda: None), job, writer)
            engine = Engine(writer, runtime, provider=object())
            state = State(run_id=job['id'], status='NEEDS_USER_INPUT', user_request='input', blocking_questions=['[Q1] first?', '[Q2] second?'])
            if fail_queue:
                async def reject(*_args, **_kwargs):
                    raise RuntimeError('queue unavailable')
                monkeypatch.setattr(store, 'enqueue_stage', reject)
                with pytest.raises(KnowledgeError):
                    await engine._answer(state, [{'question_id': 'Q1', 'question': 'first?', 'answer': 'yes'}])
                with pytest.raises(ArtifactError):
                    await writer.read_text('analysis/requirement_lock_sheet.json')
                assert writer.changed == {}
                assert state.confirmed_user_sources == {}
            else:
                result = await engine._answer(state, [{'question_id': 'Q1', 'question': 'first?', 'answer': 'yes'}])
                assert result.blocking_questions == ['[Q2] second?']
                assert (await writer.read_json('analysis/requirement_lock_sheet.json'))['user_answers'][0]['answer'] == 'yes'
                async with store.transaction(mode='read') as conn:
                    row = await (await conn.execute('SELECT stage,state FROM projection_queue WHERE job_id=%s', (job['id'],))).fetchone()
                assert row['stage'] == 'input'
                assert row['state']['confirmed_user_sources']['user_answer:Q1'] == 'yes'
                assert await store.process_projection()
                async with store.transaction(mode='read') as conn:
                    node = await (await conn.execute("SELECT body,attrs FROM nodes WHERE job_id=%s AND logical_key='user_answer:Q1' AND active", (job['id'],))).fetchone()
                assert node['body'] == 'yes' and node['attrs']['status'] == 'confirmed'
    run(scenario())


@pytest.mark.parametrize('action', ['generate', 'answer'])
def test_execution_admission_rolls_back_when_input_receipt_enqueue_fails(async_store_factory, monkeypatch, action):
    from backend.knowledge.config import KnowledgeError
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('admission atomic')
            job = {'id': 'admission-atomic', 'project_id': project['id'], 'execution_id': 'run',
                   'action': action, 'request': 'request', 'status': 'queued'}
            if action == 'answer':
                await store.save_job({**job, 'status': 'idle'})
            async def reject(*_args, **_kwargs):
                raise RuntimeError('queue unavailable')
            monkeypatch.setattr(store, 'enqueue_stage', reject)
            with pytest.raises(KnowledgeError):
                if action == 'generate':
                    await store.accept_job(job, 'request')
                else:
                    await store.record_action(job, [{'question_id': 'Q1', 'answer': 'unvalidated'}])
            async with store.transaction(mode='read') as conn:
                execution = await (await conn.execute('SELECT id FROM executions WHERE id=%s', ('run',))).fetchone()
                saved = await (await conn.execute('SELECT data FROM jobs WHERE id=%s', (job['id'],))).fetchone()
            assert execution is None
            assert saved is None if action == 'generate' else saved['data']['status'] == 'idle'
    run(scenario())


def test_accepted_raw_answer_is_indexed_as_received_not_confirmed(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('raw answer')
            job = {'id': 'raw-answer', 'project_id': project['id'], 'execution_id': 'run',
                   'action': 'answer', 'request': 'request'}
            await store.save_job(job)
            await store.record_action(job, [{'question_id': 'Q1', 'answer': 'unvalidated'}])
            assert await store.process_projection()
            async with store.transaction(mode='read') as conn:
                rows = await (await conn.execute('SELECT kind,body,attrs FROM nodes WHERE job_id=%s AND active', (job['id'],))).fetchall()
            assert len(rows) == 1 and rows[0]['kind'] == 'input'
            assert rows[0]['attrs']['status'] == 'received'
            assert 'unvalidated' in rows[0]['body']
    run(scenario())


def test_accepted_input_does_not_make_prior_index_current_before_normalization(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('input freshness')
            job = {'id': 'input-freshness', 'project_id': project['id'], 'execution_id': 'run',
                   'action': 'answer', 'request': 'request', 'status': 'running'}
            await store.save_job(job)
            await store.record_action(job, [{'question_id': 'Q1', 'answer': 'new'}])
            assert await store.process_projection()
            assert not await store.projection_ready(job['id'])
            assert (await store.projection_status(job['id']))['index_status'] == 'pending'
            await store.save_job({**job, 'status': 'error'})
            assert await store.projection_ready(job['id'])
            assert (await store.projection_status(job['id']))['index_status'] == 'ready'
            await store.save_job(job)
            async with store.transaction() as conn:
                await store.enqueue_stage(job, 'run', 'input', {'user_request': 'request'}, {}, connection=conn)
            assert await store.process_projection()
            assert await store.projection_ready(job['id'])
    run(scenario())


def test_cancelled_stage_never_commits_staged_document(async_store_factory, monkeypatch):
    from backend.infrastructure.workflow_store import TaskJournal
    from backend.knowledge.core import Documents
    from backend.errors import ArtifactError
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('cancel stage')
            job = {'id': 'cancel-stage', 'project_id': project['id'], 'execution_id': 'run', 'request': 'input'}
            await store.save_job(job)
            writer = Documents(store, job['id'])
            runtime = RunKnowledge(SimpleNamespace(store=store, schedule=lambda: None), job, writer)
            workflow = AgentWorkflow(SimpleNamespace(runtime=runtime), None, writer, SimpleNamespace(to_dict=lambda: {}))
            workflow.journal = TaskJournal(store, job['id'])
            ready = asyncio.Event()
            async def operation(_state):
                await writer.write_text('draft/approval_candidate_spec.ko.md', 'not committed')
                ready.set()
                await asyncio.Event().wait()
            task = asyncio.create_task(workflow.durable('spec_compile', {'run_id': 'run'}, operation))
            await asyncio.wait_for(ready.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(ArtifactError):
                await writer.read_text('draft/approval_candidate_spec.ko.md')
            async with store.transaction(mode='read') as conn:
                assert (await (await conn.execute('SELECT count(*) AS total FROM projection_queue')).fetchone())['total'] == 0
    run(scenario())


def test_immutable_document_same_content_can_be_written_again_in_stage(async_store_factory):
    from backend.knowledge.core import Documents
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('immutable repeat')
            await store.save_job({'id': 'immutable', 'project_id': project['id'], 'request': 'input'})
            writer = Documents(store, 'immutable')
            await writer.write_text('completed/doc.json', 'same', overwrite=False)
            before = await writer.reference('completed/doc.json')
            with writer.stage_writes() as stage:
                await writer.write_text('completed/doc.json', 'same', overwrite=False)
                assert await writer.reference('completed/doc.json') == before
            async with store.transaction():
                await writer.flush_stage(stage)
            assert await writer.reference('completed/doc.json') == before
    run(scenario())


def test_staged_overwrite_preserves_earlier_version_references(async_store_factory):
    from backend.knowledge.core import Documents
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project('staged versions')
            await store.save_job({'id': 'versioned', 'project_id': project['id'], 'request': 'input'})
            writer = Documents(store, 'versioned')
            with writer.stage_writes() as stage:
                await writer.write_text('draft/spec.md', 'first')
                first = await writer.reference('draft/spec.md')
                await writer.write_text('draft/spec.md', 'second')
                second = await writer.reference('draft/spec.md')
                assert await writer.version(first) == 'first'
            async with store.transaction():
                await writer.flush_stage(stage)
            assert await writer.version(first) == 'first'
            assert await writer.version(second) == 'second'
            assert await writer.read_text('draft/spec.md') == 'second'
    run(scenario())


def test_failed_stage_blocks_its_job_but_not_other_jobs_and_can_retry(async_store_factory, monkeypatch):
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project("queue failure")
            first = {"id": "failed-job", "project_id": project["id"], "request": "input"}
            second = {"id": "other-job", "project_id": project["id"], "request": "input"}
            await store.save_job(first)
            await store.save_job(second)
            async with store.transaction() as conn:
                await store.enqueue_stage(first, "run", "requirement_lock", {"user_request": "bad"}, {}, connection=conn)
                await store.enqueue_stage(first, "run", "requirement_lock", {"user_request": "later"}, {}, connection=conn)
                await store.enqueue_stage(second, "run", "requirement_lock", {"user_request": "other"}, {}, connection=conn)
            from backend.knowledge import projection_queue
            original = projection_queue.project
            def fail_first(job_id, state, artifacts, stage):
                if state.get("user_request") == "bad":
                    raise ValueError("invalid source")
                return original(job_id, state, artifacts, stage)
            monkeypatch.setattr(projection_queue, "project", fail_first)
            assert await store.process_projection()
            assert (await store.projection_status(first["id"]))["index_status"] == "failed"
            assert await store.process_projection()
            assert (await store.projection_status(second["id"]))["index_status"] == "ready"
            assert not await store.process_projection()
            monkeypatch.setattr(projection_queue, "project", original)
            async with store.transaction() as conn:
                await conn.execute("UPDATE projection_queue SET next_attempt=0 WHERE job_id=%s", (first["id"],))
            assert await store.process_projection()
            assert await store.process_projection()
            assert (await store.projection_status(first["id"]))["index_status"] == "ready"
    run(scenario())


def test_impact_analysis_does_not_use_stale_projection():
    async def scenario():
        from backend.knowledge.impact import impact_context
        class Store:
            async def projection_ready(self, job_id):
                assert job_id == "job"
                return False
            async def state(self, _job_id):
                raise AssertionError("stale impact was evaluated")
        with pytest.raises(ValueError, match="검색 데이터 반영 중"):
            await impact_context(Store(), "job")
    run(scenario())


def test_job_summary_reports_index_state():
    async def scenario():
        from backend.application.job_queries import JobQueries
        expected = {"index_status": "pending", "index_source_revision": 4, "index_applied_revision": 3}
        access = SimpleNamespace(
            documents=AsyncMock(return_value=None), get=AsyncMock(return_value={"id": "job", "status": "running"}),
            read_json=AsyncMock(return_value=None), read_text=AsyncMock(return_value=None), state=AsyncMock(return_value={}),
            knowledge=SimpleNamespace(store=SimpleNamespace(projection_status=AsyncMock(return_value=expected))),
        )
        summary = await JobQueries(access).summary("job")
        assert all(summary[key] == value for key, value in expected.items())
    run(scenario())


def test_retrieval_does_not_reuse_stale_job_nodes():
    async def scenario():
        class Store:
            config = SimpleNamespace(model_path=None, device="cpu")
            async def projection_ready(self, job_id):
                return job_id != "stale"
            async def graph(self, **_kwargs):
                return {"nodes": [], "edges": []}
            async def node_records(self, ids):
                return {ident: {"id": ident, "job_id": "fresh", "project_id": "p", "kind": "decision",
                                "active": True, "body": ident, "attrs": {"scope": "product"}}
                        for ident in ids}
        service = KnowledgeService(Store(), embedder=SimpleNamespace(close=lambda: None))
        service.search = AsyncMock(return_value={"mode": "text", "nodes": [
            {"id": "old", "job_id": "stale"}, {"id": "new", "job_id": "fresh"}]})
        try:
            assert [item["id"] for item in (await service.context("q", project_id="p"))["nodes"]] == ["new"]
        finally:
            await service.close()
    run(scenario())


def test_search_exposes_the_matching_scope_index_state():
    async def scenario():
        class Store:
            config = SimpleNamespace(model_path=None, device="cpu")
            async def active_model(self):
                return None
            async def search(self, *_args, **_kwargs):
                return {"nodes": [], "mode": "text"}
            async def projection_status(self, job_id=None, *, project_id=None):
                assert (job_id, project_id) == ("j", "p")
                return {"index_status": "pending", "index_source_revision": 9, "index_applied_revision": 8}
        service = KnowledgeService(Store(), embedder=SimpleNamespace(model=None, close=lambda: None))
        try:
            result = await service.search("query", project_id="p", job_id="j")
            assert result["index_status"] == "pending"
            assert result["index_source_revision"] == 9 and result["index_applied_revision"] == 8
        finally:
            await service.close()
    run(scenario())
