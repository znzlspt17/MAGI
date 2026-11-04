"""저장·서버 재시작·API·브라우저를 잇는 실행 이력 검증."""
from backend.server.execution_history import ExecutionHistory


def test_31_snapshots_survive_service_restart_and_step_api(store, monkeypatch):
    from backend.knowledge.core import Documents
    from backend.models import IssuePacket
    from gateway.app import create_app
    from tests.support.workflow_helpers import manager_for

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
        response = client.get(f"/api/jobs/{ident}")
        assert response.status_code == 200
        event = response.json["session_events"][0]
        assert event["input"] == {"request": "보스 격파 후 무기 유지 명세"}
        assert event["started_at"]
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
        from tests.e2e.browser_runtime import gateway_server, run_browser
        import json
        with gateway_server(app) as url:
            run_browser("step_history_ui.mjs", url, ident, json.dumps([step_id for step_id, _ in snapshots]))
    finally:
        reopened.close()
