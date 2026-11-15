import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.infrastructure.conversation_state import initial_messages


def test_initial_messages_loads_documents_asynchronously(monkeypatch):
    async def scenario():
        documents = SimpleNamespace(job_id="j", state={"original_user_request": "input"}, store=SimpleNamespace())
        root = SimpleNamespace(exists=AsyncMock(return_value=False), read_text=AsyncMock())
        monkeypatch.setattr("backend.knowledge.core.Documents", lambda *_: root)
        messages = await initial_messages(documents, {})
        assert "input" in messages[1]["content"][0]["text"]
        assert root.exists.await_count == 2
    asyncio.run(scenario())
