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


def test_uncertain_model_call_requires_consent_and_restart_does_not_call_model(
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
    assert manager.workspace.allowed(ident) == ["message", "retry"]
    assert manager.workspace.summary(ident)["retry_requires_replay"]
    with pytest.raises(CleanupConflict):
        manager.retry(ident, manager.get(ident)["execution_id"])
    # 배포 전 저널은 호출 횟수 없이 빈 payload만 남겼으므로 보수적으로 취급한다.
    with store.transaction() as conn:
        conn.execute("UPDATE workflow.workflow_task_results SET payload='{}' WHERE thread_id=%s AND status='pending'",(ident,))
    manager.close()
    restored, _ = manager_for(store, monkeypatch, provider)
    try:
        assert len(provider.calls) == before
        provider.broken = False
        restored.retry(ident,restored.get(ident)["execution_id"],replay_pending=True)
        restored._run(ident,"retry",{"replay_pending":True})
        assert restored.get(ident)["status"] == "PASS_PENDING_USER_APPROVAL"
        import json
        with store.transaction(mode="read") as conn:
            histories = [json.loads(row["payload"]).get("previous_attempts", []) for row in conn.execute("SELECT payload FROM workflow.workflow_task_results").fetchall()]
        assert any(h and h[-1]["status"] == "pending" for h in histories)
    finally:
        restored.close()


@pytest.mark.parametrize("called", [False, True])
def test_task_failure_tracks_all_calls_and_replay_is_scoped(store, called):
    import json
    from backend.access.context import AccessError
    from backend.infrastructure.workflow_store import workflow_store, provider_entered
    from backend.pipeline.agent_workflow import task_id
    from backend.infrastructure.evidence_registry import EvidenceRegistry

    docs = Documents(store,"task-observation")
    workflow = AgentWorkflow(None,None,docs,EvidenceRegistry())
    workflow.persist = Mock()
    state = {"run_id":"task-observation","revision":0,"plan_history":[]}
    ident, other = task_id(state,"requirement_lock"), task_id(state,"interview")
    with workflow_store(store,docs.job_id) as (_,journal):
        workflow.journal = journal
        def fail(current):
            if called:
                # 첫 호출은 완료됐지만 그 뒤 보정 호출의 예약이 차단된 과거 경로.
                provider_entered()
            raise AccessError("test quota","quota")
        with pytest.raises(AccessError):
            workflow.durable("requirement_lock",state,fail)
        assert journal.status(ident) == ("pending" if called else "failed")
        row = journal.conn.execute("SELECT payload FROM workflow_task_results WHERE thread_id=%s AND task_id=%s",(docs.job_id,ident)).fetchone()
        assert json.loads(row["payload"])["call_count"] == int(called)
        journal.begin(other)
        if called:
            from backend.errors import InvalidStateError
            with pytest.raises(InvalidStateError):
                workflow.durable("requirement_lock",state,lambda _: {})
            workflow.replay_task_id = ident
        assert workflow.durable("requirement_lock",state,lambda _: {"restored":True})["restored"]
        assert journal.status(ident) == "completed" and journal.status(other) == "pending"
        payload = journal.conn.execute("SELECT payload FROM workflow_task_results WHERE thread_id=%s AND task_id=%s",(docs.job_id,ident)).fetchone()["payload"]
        assert json.loads(payload)["previous_attempts"][-1]["payload"]["call_count"] == int(called)


def test_missing_and_unsupported_checkpoint_have_specific_retry_reasons(store,monkeypatch):
    from backend.infrastructure.workflow_store import retry_state
    manager, _ = manager_for(store,monkeypatch)
    try:
        job = manager.create("메모를 저장해주세요")
        manager.jobs[job["id"]]["status"] = "error"
        store.save_job(manager.jobs[job["id"]])
        summary = manager.workspace.summary(job["id"])
        assert not summary["can_retry"] and "checkpoint가 없어" in summary["retry_unavailable_reason"]
        docs = SimpleNamespace(workflow_snapshot=lambda:SimpleNamespace(values={"workflow_schema":999},next=("planner",),tasks=[]))
        assert "형식이 올바르지" in retry_state(docs)["retry_unavailable_reason"]
    finally:
        manager.close()


def test_planned_review_question_recovers_uncertain_call_and_resumes_with_answer(store, monkeypatch):
    import json
    from backend.config import Config
    from backend.models import ReviewResolutionResponse
    from backend.pipeline.planner import PlannerDecision
    from prompt_fixtures import model_context, planner_result

    issue = dict(section="functional_requirements", severity="major", checklist_id="retention",
                 problem="보관 기간이 확정되지 않았습니다.", required_change="보관 기간을 반영하세요.",
                 requirement_id="REQ-001", evidence=[{"source": "draft", "quote": "Store notes locally."}],
                 defect_kind="spec_omission", resolution_kind="auto_fix", resolution_reason="보완이 필요합니다.",
                 missing_information="", decision_key="retention", decision_question=None)

    class Provider(DecisionProvider):
        fail_question = True
        planner_payloads = []

        def complete_result(self, messages, **kwargs):
            schema = kwargs["text_format"]
            if schema is PlannerDecision:
                payload = json.loads(next(item["content"] for item in messages if item["role"] == "user"))
                self.planner_payloads.append(payload)
                result = planner_result(messages)
                answered = any(ref.startswith("user_answer:REVIEW-") for ref in payload.get("confirmed_user_sources", {}))
                if payload.get("resolution_history") and payload["execution_constraints"]["repair_limit_reached"] and not answered:
                    result.parsed.action = "ask_user"
                    result.parsed.target = "메모 보관 기간"
                    result.parsed.reason = "보완 이력만으로 보관 기간을 확정할 수 없습니다."
                return result
            canonical = model_context(messages)
            asking = schema is ReviewResolutionResponse and canonical.get("planner_intent", {}).get("action") == "ask_user"
            if asking and self.fail_question:
                raise Error("test uncertain question call")
            result = super().complete_result(messages, **kwargs)
            if asking:
                for item in result.parsed.resolutions:
                    item.defect_kind = "requirements_gap"
                    item.resolution_kind = "user_decision"
                    item.missing_information = "메모 보관 기간에 따라 삭제 동작이 달라집니다."
                    item.decision_question = "메모를 며칠 동안 보관할까요?"
                    item.impact = "data"
            return result

    provider = Provider([[issue], []])
    manager, _ = manager_for(store, monkeypatch, provider)
    manager.workspace.engine_factory = lambda docs, runtime: Engine(docs, runtime, provider=provider, config=Config(max_critic_passes=1))
    try:
        ident = manager.create("메모를 저장해주세요")["id"]
        manager._run(ident, "generate", None)
        assert manager.get(ident)["status"] == "error"
        assert manager.workspace.summary(ident)["retry_requires_replay"]
        with pytest.raises(CleanupConflict):
            manager.retry(ident, manager.get(ident)["execution_id"])
        provider.fail_question = False
        manager.retry(ident, manager.get(ident)["execution_id"], replay_pending=True)
        manager._run(ident, "retry", {"replay_pending": True})
        state = manager.workspace.state(ident)
        assert state["status"] == "NEEDS_USER_INPUT"
        assert state["critic_pass_count"] == 1
        assert state["awaiting_input_reason"] == "review"
        qid = state["review_questions"][-1]["question_id"]
        assert qid in state["question_forms"]
        assert provider.contexts[ReviewResolutionResponse]["final_assessment"] is True
        answers = [{"question_id": qid, "question": state["blocking_questions"][0], "answer": "30일"}]
        manager.action(ident, "answer", answers, expected_execution_id=manager.get(ident)["execution_id"])
        manager._run(ident, "answer", answers)
        assert manager.get(ident)["status"] == "PASS_PENDING_USER_APPROVAL"
        assert provider.calls.count(InterviewResponse) == 1
        assert any(payload.get("confirmed_user_sources", {}).get("user_answer:" + qid) == "30일"
                   for payload in provider.planner_payloads)
    finally:
        manager.close()


def test_blocked_checkpoint_can_retry_through_new_planner_without_final_assessment_cache(store, monkeypatch):
    from backend.pipeline.planner import PlannerDecision
    from prompt_fixtures import planner_result

    class Provider(DecisionProvider):
        plans = 0

        def complete_result(self, messages, **kwargs):
            if kwargs["text_format"] is PlannerDecision:
                self.plans += 1
                result = planner_result(messages)
                result.parsed.action = "blocked" if self.plans == 1 else "ask_user"
                return result
            result = super().complete_result(messages, **kwargs)
            if kwargs["text_format"] is InterviewResponse:
                from backend.models import QuestionResponse
                result.parsed.blocking_questions = [QuestionResponse(question_id="RETENTION", question="메모 보관 기간은 얼마인가요?")]
            return result

    manager, provider = manager_for(store, monkeypatch, Provider([[]]))
    try:
        ident = manager.create("메모를 저장해주세요")["id"]
        manager._run(ident, "generate", None)
        assert manager.get(ident)["status"] == "CRITICAL_BLOCKED"
        manager.retry(ident, manager.get(ident)["execution_id"])
        manager._run(ident, "retry", None)
        assert manager.get(ident)["status"] == "NEEDS_USER_INPUT"
        assert provider.plans == 2
        assert provider.calls.count(InterviewResponse) == 1
    finally:
        manager.close()


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
