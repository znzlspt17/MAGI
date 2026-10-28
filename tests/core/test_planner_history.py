"""실행별 계획의 공개 판단 내용을 변경 시점 그대로 보존한다."""

from types import SimpleNamespace

from backend.server.execution_history import ExecutionHistory


def test_capture_planner_preserves_public_result_only():
    history = ExecutionHistory(SimpleNamespace())
    data = {"nodes": [{"id": "plan-1", "execution_id": "execution", "stage": "planner", "detail_available": True}]}
    history._load = lambda **kwargs: data
    history._save = lambda value: None
    plan = {"goal": "무기 처리 명세 보완", "action": "spec_compile", "reason": "확정 답변을 초안에 반영합니다.",
            "target": "보스 격파 후 무기 유지", "tasks": [{"id": "fix", "title": "무기 유지 반영", "status": "pending"}],
            "expected_result": "수정된 초안", "internal_messages": ["not a public result"]}
    history.capture("execution", "planner", state={"plan": plan})
    plan["tasks"][0]["title"] = "이후 변경"
    result = history.detail("plan-1")
    assert result["result"]["plan"]["reason"] == "확정 답변을 초안에 반영합니다."
    assert result["result"]["plan"]["tasks"][0]["title"] == "무기 유지 반영"
    assert "internal_messages" not in result["result"]["plan"]
    assert result["summary"] == "확정 답변을 초안에 반영합니다."


def test_old_planner_history_does_not_invent_a_plan():
    history = ExecutionHistory(SimpleNamespace())
    history._load = lambda **kwargs: {"nodes": [{"id": "old", "stage": "planner", "summary": "상세 결과 기록 없음"}]}
    assert "plan" not in history.detail("old")["result"]


def test_progress_keeps_plan_and_safe_failure_diagnostic():
    from backend.pipeline.builder import _progress, _stage
    from backend.errors import SpecCompilationError
    import pytest

    events = []
    _progress(events.append, "planner", "completed", {"plan": {"reason": "확정 근거 확인", "raw_response": "do not store"}})
    assert events[-1]["result"] == {"plan": {"reason": "확정 근거 확인"}}

    def fail(state):
        raise SpecCompilationError(["untrusted response"], check="spec_blocks")

    with pytest.raises(SpecCompilationError):
        _stage("spec_compile", fail, events.append)({})
    failed = events[-1]
    assert failed["state"] == "failed"
    assert failed["result"]["diagnostic"]["error_code"] == "SPEC_COMPILATION_INVALID"
    assert "frames" not in failed["result"]["diagnostic"]
    assert "untrusted response" not in str(failed)


def test_failed_step_keeps_diagnostic_after_later_success(store, monkeypatch):
    from backend.knowledge.core import Documents
    from test_workflow import manager_for

    manager, _ = manager_for(store, monkeypatch)
    try:
        job = manager.create("실패 이력 보존 검증")
        history = ExecutionHistory(manager.workspace.documents(job["id"]))
        execution = job["execution_id"]
        history.stage(execution, "spec_compile", "started")
        history.stage(execution, "spec_compile", "failed", result={"diagnostic": {
            "error_code": "SPEC_COMPILATION_INVALID", "error_stage": "spec_compile",
            "failed_checks": ["spec_blocks"], "frames": ["excluded"], "raw_response": "excluded",
        }})
        failed_id = history.graph()["nodes"][-1]["id"]
        history.stage(execution, "spec_compile", "started")
        history.stage(execution, "spec_compile", "completed")
        restored = ExecutionHistory(Documents(store, job["id"])).detail(failed_id)
        assert restored["status"] == "failed"
        assert restored["result"]["diagnostic"] == {
            "error_code": "SPEC_COMPILATION_INVALID", "error_stage": "spec_compile", "failed_checks": ["spec_blocks"],
        }
    finally:
        manager.close()


def test_31_snapshots_survive_service_restart_and_step_api(store, monkeypatch):
    from backend.knowledge.core import Documents
    from backend.models import IssuePacket
    from gateway.app import create_app
    from test_workflow import manager_for

    manager, _ = manager_for(store, monkeypatch)
    job = manager.create("보스 격파 후 무기 유지 명세")
    ident, execution = job["id"], job["execution_id"]
    docs = manager.workspace.documents(ident)
    snapshots = []
    try:
        for index in range(31):
            stage = "planner" if index % 2 == 0 else "review_resolution"
            manager._engine_progress(ident, {"stage": stage, "state": "started"})
            if stage == "planner":
                result = {"plan": {"goal": f"목표 {index}", "action": "spec_compile", "reason": f"판단 근거 {index}",
                                   "target": "보스 격파 후 무기 유지", "expected_result": f"초안 {index}",
                                   "input_refs": ["user_answer:Q1"], "tasks": [], "raw_response": "excluded"}}
            else:
                issue = IssuePacket(f"I{index}", "weapons", "major", True, "boss_weapon",
                                    f"결함 {index}", f"보완 {index}", decision_key="boss_weapon",
                                    resolution_kind="auto_fix", resolution_reason=f"해결 판단 {index}",
                                    decision_answer_id="Q1", basis_refs=["user_answer:Q1"])
                docs.write_text("draft/approval_candidate_spec.en.md", f"# Draft {index}", overwrite=True)
                docs.write_json("review/resolution.json", {"issues": [issue.to_dict()], "pass": index,
                                                          "action": "repair", "draft_hash": str(index), "diagnosed_keys": []}, overwrite=True)
                result = {"structured_issues": [issue.to_dict()]}
            manager._engine_progress(ident, {"stage": stage, "state": "completed", "result": result})
            node = ExecutionHistory(docs).graph()["nodes"][-1]
            snapshots.append((node["id"], manager.workspace.step(ident, node["id"])))
        # 현재 문서와 상태를 바꿔도 이전 단계의 문서·판단은 변하지 않는다.
        docs.write_text("draft/approval_candidate_spec.en.md", "# Later draft", overwrite=True)
        job.update(status="CRITICAL_BLOCKED")
        store.save_job(job)
    finally:
        manager.close()

    reopened, _ = manager_for(store, monkeypatch)
    try:
        class SavedStepClient:
            def __init__(self, url):
                pass

            def call(self, method, params=None):
                if method == "list":
                    return [reopened.workspace.public(ident)]
                if method == "projects.list":
                    return []
                assert method == "get"
                if params.get("step_id"):
                    return reopened.workspace.step(params["id"], params["step_id"])
                return reopened.workspace.public(params["id"])

            def events(self):
                yield {"event": "ready"}

        app = create_app({"TESTING": True, "PUBLIC_MODE": False, "CLIENT_FACTORY": SavedStepClient})
        client = app.test_client()
        assert len(snapshots) == 31
        for index, (step_id, expected) in enumerate(snapshots):
            response = client.get(f"/api/jobs/{ident}/steps/{step_id}")
            assert response.status_code == 200
            assert response.json == expected
            if index % 2 == 0:
                assert response.json["result"]["plan"]["reason"] == f"판단 근거 {index}"
                assert "raw_response" not in response.json["result"]["plan"]
            else:
                assert response.json["result"]["issues"][0]["problem"] == f"결함 {index}"
                assert response.json["result"]["action"] == "repair"
                assert response.json["document"]["content"] == f"# Draft {index}"
        assert ExecutionHistory(Documents(store, ident)).detail(snapshots[0][0])["result"]["plan"]["reason"] == "판단 근거 0"
        from browser_runtime import gateway_server, run_browser
        import json
        with gateway_server(app) as url:
            run_browser("step_history_ui.mjs", url, ident, json.dumps([step_id for step_id, _ in snapshots]))
    finally:
        reopened.close()
