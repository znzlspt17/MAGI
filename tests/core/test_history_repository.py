"""DB 조회 실패와 JSON 기록 손상을 구분한다."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from backend.infrastructure.history_repository import HistoryRepository


def repository(events, executions):
    class Connection:
        def execute(self, sql, params):
            rows = events if "execution_events" in sql else executions
            return SimpleNamespace(fetchall=lambda: rows)

    @contextmanager
    def transaction(**kwargs):
        yield Connection()

    return HistoryRepository(SimpleNamespace(job_id="job", store=SimpleNamespace(transaction=transaction)),
                             lambda action, value: {"request": value})


def test_bad_json_row_does_not_hide_valid_history():
    history = repository([{"data": []}, {"data": {"id": "valid", "stage": "planner"}}], [])
    result = history.load()
    assert result["nodes"] == [{"id": "valid", "stage": "planner"}]
    assert result["recording_incomplete"] is True


def test_missing_execution_reference_does_not_crash_legacy_action():
    result = repository([{"data": {"id": "legacy", "action": "generate"}}], []).load()
    assert result["nodes"][0]["id"] == "legacy"
    assert result["recording_incomplete"] is True


def test_database_failure_is_not_presented_as_empty_history():
    @contextmanager
    def unavailable(**kwargs):
        raise ConnectionError("test database unavailable")
        yield

    history = HistoryRepository(SimpleNamespace(store=SimpleNamespace(transaction=unavailable)), None)
    with pytest.raises(ConnectionError):
        history.load()
