"""DB 문서·공식 그래프·서버 명령이 만나는 제품 경계."""

from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from backend.engine import Engine
from backend.knowledge.core import Documents
from backend.server.job_manager import JobManager
from backend.server.cleanup import CleanupConflict
from fakes import DecisionProvider
from backend.models import InterviewResponse, SpecDraftResponse, CompletionResult
from backend.errors import Error
from backend.pipeline.agent_workflow import AgentWorkflow


def manager_for(store, monkeypatch, provider=None):
    service = SimpleNamespace(
        store=store,
        close=lambda: None,
        schedule=lambda: None,
        context=lambda *a, **kw: {"nodes": [], "edges": [], "mode": "text"},
    )
    provider = provider or DecisionProvider([[], [], [], []])
    manager = JobManager(
        service,
        engine_factory=lambda docs, runtime: Engine(docs, runtime, provider=provider),
    )
    monkeypatch.setattr(manager, "_submit_locked", Mock())
    return manager, provider


def test_documents_deduplicate_content_and_keep_versions(store):
    project = store.create_project("문서")
    store.save_job({"id": "a" * 32, "project_id": project["id"]})
    docs = Documents(store, "a" * 32)
    docs.write_text("draft/spec.md", "first")
    original = docs.reference("draft/spec.md")
    docs.write_text("draft/spec.md", "first")
    assert docs.reference("draft/spec.md") == original
    docs.write_text("draft/spec.md", "second")
    assert docs.version(original) == "first"
    with store.transaction(mode="read") as conn:
        assert (
            conn.execute("SELECT count(*) AS total FROM document_bodies").fetchone()[
                "total"
            ]
            == 2
        )


def test_generate_approve_and_explicit_revision(store, monkeypatch):
    manager, provider = manager_for(store, monkeypatch)
    try:
        ident = manager.create("메모를 저장해주세요")["id"]
        manager._run(ident, "generate", None)
        assert manager.get(ident)["status"] == "PASS_PENDING_USER_APPROVAL"
        job = manager.get(ident)
        with pytest.raises(CleanupConflict):
            manager.action(ident, "approve", None, expected_execution_id="stale")
        manager.action(
            ident,
            "approve",
            {"candidate_hash": manager.workspace.state(ident)["candidate_hash"]},
            expected_execution_id=job["execution_id"],
        )
        manager._run(
            ident,
            "approve",
            {"candidate_hash": manager.workspace.state(ident)["candidate_hash"]},
        )
        assert manager.get(ident)["status"] == "FINALIZED"
        completed = manager.workspace.state(ident)["latest_completed"]
        original = manager.workspace.documents(ident).read_text(completed["path"])
        bundle = manager.workspace.implementation_package(ident, {})
        assert bundle["available"] is True
        review = manager.workspace.requirement_review(ident, {})
        assert review["status"] != "unavailable"
        from backend.knowledge.impact import impact_context

        context = impact_context(store, ident)
        assert context["nodes"]
        candidates = manager.workspace.decision_candidates(ident, {})
        # 가짜 모델은 공통 결정을 만들지 않는다. 승인만으로 결정을 추정하지 않는다.
        assert candidates["rows"] == []
        job = manager.get(ident)
        manager.action(
            ident,
            "message",
            "메모를 저장해주세요",
            expected_execution_id=job["execution_id"],
        )
        manager._run(ident, "message", "메모를 저장해주세요")
        assert manager.get(ident)["status"] == "PASS_PENDING_USER_APPROVAL"
        assert (
            manager.workspace.documents(ident).read_text(completed["path"]) == original
        )
        assert manager.workspace.public(ident)["session_events"]
    finally:
        manager.close()


def test_partial_answers_resume_official_interrupt_without_reinterview(
    store, monkeypatch
):
    class Provider(DecisionProvider):
        def complete_result(self, messages, **kwargs):
            result = super().complete_result(messages, **kwargs)
            if (
                kwargs["text_format"] is InterviewResponse
                and self.calls.count(InterviewResponse) == 1
            ):
                parsed = InterviewResponse.model_validate(
                    {
                        **result.parsed.model_dump(),
                        "blocking_questions": [
                            {
                                "question_id": "PRODUCT-001",
                                "question": "저장 방식은 무엇인가요?",
                            },
                            {
                                "question_id": "PRODUCT-002",
                                "question": "메모 보관 기간은 얼마인가요?",
                            },
                        ],
                    }
                )
                return CompletionResult(
                    text="", parsed=parsed, response_id=result.response_id
                )
            return result

    manager, provider = manager_for(store, monkeypatch, Provider([[]]))
    try:
        ident = manager.create("메모를 저장해주세요")["id"]
        manager._run(ident, "generate", None)
        assert manager.workspace.state(ident)["status"] == "NEEDS_USER_INPUT"
        snapshot = manager.workspace.documents(ident).workflow_snapshot()
        assert snapshot.tasks[0].interrupts
        first = [
            {
                "question_id": "PRODUCT-001",
                "question": "저장 방식은 무엇인가요?",
                "answer": "오프라인 저장",
            }
        ]
        manager.action(
            ident,
            "answer",
            first,
            expected_execution_id=manager.get(ident)["execution_id"],
        )
        manager._run(ident, "answer", first)
        assert len(manager.workspace.state(ident)["blocking_questions"]) == 1
        assert provider.calls.count(InterviewResponse) == 1
        second = [
            {
                "question_id": "PRODUCT-002",
                "question": "메모 보관 기간은 얼마인가요?",
                "answer": "30일",
            }
        ]
        manager.action(
            ident,
            "answer",
            second,
            expected_execution_id=manager.get(ident)["execution_id"],
        )
        manager._run(ident, "answer", second)
        assert manager.workspace.state(ident)["status"] == "PASS_PENDING_USER_APPROVAL"
        answers = manager.workspace.public(ident)["state"]["saved_answers"]
        assert {"오프라인 저장", "30일"} <= {a["answer"] for a in answers}
    finally:
        manager.close()


def test_saved_task_result_is_reused_after_projection_failure(store, monkeypatch):
    manager, provider = manager_for(store, monkeypatch)
    original = AgentWorkflow.persist
    failures = []

    def fail_once(self, stage, state):
        if stage == "spec_compile" and not failures:
            failures.append(True)
            raise RuntimeError("test projection failure")
        return original(self, stage, state)

    monkeypatch.setattr(AgentWorkflow, "persist", fail_once)
    try:
        ident = manager.create("메모를 저장해주세요")["id"]
        manager._run(ident, "generate", None)
        assert manager.get(ident)["status"] == "error"
        assert provider.calls.count(SpecDraftResponse) == 1
        manager.retry(ident, manager.get(ident)["execution_id"])
        manager._run(ident, "retry", None)
        assert manager.get(ident)["status"] == "PASS_PENDING_USER_APPROVAL"
        assert provider.calls.count(SpecDraftResponse) == 1
    finally:
        manager.close()


def test_uncertain_model_call_requires_revision_and_restart_does_not_call_model(
    store, monkeypatch
):
    class Provider(DecisionProvider):
        broken = True

        def complete_result(self, messages, **kwargs):
            if kwargs["text_format"] is InterviewResponse and self.broken:
                self.calls.append(InterviewResponse)
                raise Error("test transport failure")
            return super().complete_result(messages, **kwargs)

    provider = Provider([[]])
    manager, _ = manager_for(store, monkeypatch, provider)
    ident = manager.create("메모를 저장해주세요")["id"]
    manager._run(ident, "generate", None)
    before = len(provider.calls)
    assert manager.workspace.allowed(ident) == ["message"]
    with pytest.raises(CleanupConflict):
        manager.retry(ident, manager.get(ident)["execution_id"])
    manager.close()
    restored, _ = manager_for(store, monkeypatch, provider)
    try:
        assert len(provider.calls) == before
        provider.broken = False
        restored.action(
            ident,
            "message",
            "메모를 저장해주세요",
            expected_execution_id=restored.get(ident)["execution_id"],
        )
        restored._run(ident, "message", "메모를 저장해주세요")
        assert restored.get(ident)["status"] == "PASS_PENDING_USER_APPROVAL"
    finally:
        restored.close()


def test_delete_cleans_documents_index_and_checkpoint_once(store, monkeypatch):
    manager, provider = manager_for(store, monkeypatch)
    try:
        ident = manager.create("메모를 저장해주세요")["id"]
        manager._run(ident, "generate", None)
        assert (
            manager.workspace.documents(ident).workflow_snapshot().tasks[0].interrupts
        )
        before = len(provider.calls)
        operation = manager.cleanup.preview({"scope": "jobs", "ids": [ident]})
        result = manager.cleanup.execute({"id": operation["id"]})
        assert result["state"] == "completed"
        assert manager.cleanup.execute({"id": operation["id"]}) == result
        assert len(provider.calls) == before
        with store.transaction(mode="read") as conn:
            for table in [
                "jobs",
                "document_versions",
                "document_bodies",
                "nodes",
                "executions",
                "execution_events",
            ]:
                assert (
                    conn.execute(f"SELECT count(*) AS total FROM {table}").fetchone()[
                        "total"
                    ]
                    == 0
                )
        from backend.knowledge.core import checkpoint_store

        with checkpoint_store(store) as saver:
            assert (
                AgentWorkflow(None, None, None, None)
                .build(saver)
                .get_state({"configurable": {"thread_id": ident}})
                .values
                == {}
            )
    finally:
        manager.close()
