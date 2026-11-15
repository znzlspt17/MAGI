"""DB 조회 실패와 JSON 기록 손상을 구분한다."""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from tests.backend.application.async_helpers import run_async
from types import SimpleNamespace

import pytest

from backend.infrastructure.history_repository import HistoryRepository


def repository(events, executions):
    class Connection:
        async def execute(self, sql, params):
            rows = events if "execution_events" in sql else executions
            return SimpleNamespace(fetchall=AsyncMock(return_value=rows))

    @asynccontextmanager
    async def transaction(**kwargs):
        yield Connection()

    return HistoryRepository(SimpleNamespace(job_id="job", store=SimpleNamespace(transaction=transaction)),
                             lambda action, value: {"request": value})


@run_async
async def test_bad_json_row_does_not_hide_valid_history():
    history = repository([{"data": []}, {"data": {"id": "valid", "stage": "planner"}}], [])
    result = await history.load()
    assert result["nodes"] == [{"id": "valid", "stage": "planner"}]
    assert result["recording_incomplete"] is True


@run_async
async def test_missing_execution_reference_does_not_crash_legacy_action():
    result = await repository([{"data": {"id": "legacy", "action": "generate"}}], []).load()
    assert result["nodes"][0]["id"] == "legacy"
    assert result["recording_incomplete"] is True


@run_async
async def test_database_failure_is_not_presented_as_empty_history():
    @asynccontextmanager
    async def unavailable(**kwargs):
        raise ConnectionError("test database unavailable")
        yield

    history = HistoryRepository(SimpleNamespace(store=SimpleNamespace(transaction=unavailable)), None)
    with pytest.raises(ConnectionError):
        await history.load()
