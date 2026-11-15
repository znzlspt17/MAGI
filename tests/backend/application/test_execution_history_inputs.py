"""사용자 작업 노드 누락과 실행 접수 순서의 회귀 검증."""
from copy import deepcopy
from unittest.mock import AsyncMock
from tests.backend.application.async_helpers import run_async

from backend.application.execution_history import ExecutionHistory


def history_for(data):
    history = ExecutionHistory(None)
    history._load = AsyncMock(side_effect=lambda **kwargs: deepcopy(data))
    history._save = AsyncMock(side_effect=lambda saved: (data.clear(), data.update(saved)))
    return history


@run_async
async def test_registered_execution_records_input_node_and_time_once():
    data = {"nodes": [], "executions": [
        {"id": "run", "action": "generate", "input": "게임 요구사항", "status": "queued"},
    ]}
    history = history_for(data)
    (await history.start_execution("generate", "run", input_data="게임 요구사항"))
    first = deepcopy(data)
    (await history.start_execution("generate", "run", input_data="게임 요구사항"))
    assert data == first
    assert len(data["executions"]) == len(data["nodes"]) == 1
    event = (await history.conversation())[0]
    assert event["input"] == {"request": "게임 요구사항"}
    assert event["started_at"] == data["nodes"][0]["started_at"]


@run_async
async def test_existing_history_reads_saved_input_without_action_nodes():
    answers = [{"question_id": "Q1", "question": "대상 플랫폼은?", "answer": "PC"}]
    data = {"nodes": [], "executions": [
        {"id": "first", "action": "generate", "input": "게임 요구사항"},
        {"id": "second", "action": "answer", "input": answers},
    ]}
    events = (await history_for(data).conversation())
    assert events[0]["input"] == {"request": "게임 요구사항"}
    assert events[1]["input"] == {"answers": answers}
    assert events[0]["started_at"] is None


@run_async
async def test_retry_updates_matching_execution_and_preserves_timestamp():
    timestamp = "2026-11-03T00:00:00+00:00"
    data = {"nodes": [], "executions": [
        {"id": "retry", "action": "retry", "started_at": timestamp},
        {"id": "other", "action": "generate"},
    ]}
    (await history_for(data).start_execution("retry", "retry", input_data={"retry_of": "original"}))
    assert data["executions"][0]["retry_of"] == "original"
    assert data["executions"][0]["started_at"] == timestamp
    assert "retry_of" not in data["executions"][1]


@run_async
async def test_legacy_input_node_is_used_when_execution_has_no_input():
    data = {"nodes": [{"execution_id": "run", "action": "generate",
                       "result": {"request": "이전 요청"}}],
            "executions": [{"id": "run", "action": "generate"}]}
    assert (await history_for(data).conversation())[0]["input"] == {"request": "이전 요청"}


@run_async
async def test_saved_executions_without_nodes_survive_reload(async_store_factory):
    from backend.knowledge.core import Documents
    async with async_store_factory() as store:
        job = {"id": "a" * 32, "project_id": "a" * 32, "request": "게임 요구사항",
               "execution_id": "first", "owner_id": None, "action": "generate"}
        await store.accept_job(job, job["request"])
        answers = [{"question_id": "Q1", "question": "대상 플랫폼은?", "answer": "PC"}]
        answer_job = {**job, "action": "answer", "execution_id": "answer-run"}
        await store.record_action(answer_job, answers)
        # 수정 전처럼 입력 노드와 접수 시각이 없는 DB 기록을 재현한다.
        async with store.transaction() as conn:
            await conn.execute("DELETE FROM execution_events WHERE job_id=%s", (job["id"],))
            await conn.execute("UPDATE executions SET timeline='{}'::jsonb WHERE job_id=%s", (job["id"],))
        events = (await ExecutionHistory(Documents(store, job["id"])).conversation())
        assert [event["input"] for event in events] == [
            {"request": "게임 요구사항"}, {"answers": answers},
        ]
        assert all(event["started_at"] is None for event in events)
