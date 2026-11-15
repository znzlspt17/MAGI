import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.pipeline.tasks import WorkflowTasks
from backend.pipeline.builder import _stage


def test_project_context_waits_for_async_document_persistence():
    async def scenario():
        tasks = WorkflowTasks.__new__(WorkflowTasks)
        tasks.writer = SimpleNamespace(write_json=AsyncMock())
        assert await tasks.project_context({}) == {}
        tasks.writer.write_json.assert_awaited_once_with("context/project_manifest.json", {"file_count": 0, "files": []})
    asyncio.run(scenario())


def test_async_stage_supports_pure_synchronous_callback_and_node():
    async def scenario():
        events = []
        result = await _stage("test", lambda state: {"value": state["value"] + 1}, events.append)({"value": 1})
        assert result == {"value": 2}
        assert [item["state"] for item in events] == ["started", "completed"]
    asyncio.run(scenario())
