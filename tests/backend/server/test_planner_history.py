"""실행별 계획의 공개 판단 내용을 변경 시점 그대로 보존한다."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from tests.backend.application.async_helpers import run_async

from backend.server.execution_history import ExecutionHistory


@run_async
async def test_capture_planner_preserves_public_result_only():
    history = ExecutionHistory(SimpleNamespace())
    data = {"nodes": [{"id": "plan-1", "execution_id": "execution", "stage": "planner", "detail_available": True}]}
    history._load = AsyncMock(return_value=data)
    history._save = AsyncMock()
    plan = {"goal": "무기 처리 명세 보완", "action": "spec_compile", "reason": "확정 답변을 초안에 반영합니다.",
            "target": "보스 격파 후 무기 유지", "tasks": [{"id": "fix", "title": "무기 유지 반영", "status": "pending"}],
            "expected_result": "수정된 초안", "internal_messages": ["not a public result"]}
    await history.capture("execution", "planner", state={"plan": plan})
    plan["tasks"][0]["title"] = "이후 변경"
    result = await history.detail("plan-1")
    assert result["result"]["plan"]["reason"] == "확정 답변을 초안에 반영합니다."
    assert result["result"]["plan"]["tasks"][0]["title"] == "무기 유지 반영"
    assert "internal_messages" not in result["result"]["plan"]
    assert result["summary"] == "확정 답변을 초안에 반영합니다."


@run_async
async def test_old_planner_history_does_not_invent_a_plan():
    history = ExecutionHistory(SimpleNamespace())
    history._load = AsyncMock(return_value={"nodes": [{"id": "old", "stage": "planner", "summary": "상세 결과 기록 없음"}]})
    assert "plan" not in (await history.detail("old"))["result"]


@run_async
async def test_progress_keeps_plan_and_safe_failure_diagnostic():
    from backend.pipeline.builder import _progress, _stage
    from backend.errors import SpecCompilationError
    import pytest

    events = []
    await _progress(events.append, "planner", "completed", {"plan": {"reason": "확정 근거 확인", "raw_response": "do not store"}})
    assert events[-1]["result"] == {"plan": {"reason": "확정 근거 확인"}}

    def fail(state):
        raise SpecCompilationError(["untrusted response"], check="spec_blocks")

    with pytest.raises(SpecCompilationError):
        await _stage("spec_compile", fail, events.append)({})
    failed = events[-1]
    assert failed["state"] == "failed"
    assert failed["result"]["diagnostic"]["error_code"] == "SPEC_COMPILATION_INVALID"
    assert "frames" not in failed["result"]["diagnostic"]
    assert "untrusted response" not in str(failed)


@run_async
async def test_failed_step_keeps_diagnostic_after_later_success(async_store_factory, monkeypatch):
    from backend.knowledge.core import Documents
    from tests.support.workflow_helpers import manager_for

    async with async_store_factory() as store:
        manager, _ = await manager_for(store, monkeypatch)
        try:
            job = await manager.create("실패 이력 보존 검증")
            history = ExecutionHistory(await manager.workspace.documents(job["id"]))
            execution = job["execution_id"]
            await history.stage(execution, "spec_compile", "started")
            await history.stage(execution, "spec_compile", "failed", result={"diagnostic": {
                "error_code": "SPEC_COMPILATION_INVALID", "error_stage": "spec_compile",
                "failed_checks": ["spec_blocks"], "frames": ["excluded"], "raw_response": "excluded",
            }})
            failed_id = (await history.graph())["nodes"][-1]["id"]
            await history.stage(execution, "spec_compile", "started")
            await history.stage(execution, "spec_compile", "completed")
            restored = await ExecutionHistory(Documents(store, job["id"])).detail(failed_id)
            assert restored["status"] == "failed"
            diagnostic = restored["result"]["diagnostic"]
            assert {key: diagnostic[key] for key in ("error_code", "error_stage", "failed_checks")} == {
                "error_code": "SPEC_COMPILATION_INVALID", "error_stage": "spec_compile", "failed_checks": ["spec_blocks"],
            }
            assert diagnostic["attempts"][0]["failed_checks"] == ["spec_blocks"]
        finally:
            await manager.close()
