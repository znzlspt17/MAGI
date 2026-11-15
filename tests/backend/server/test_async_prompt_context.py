import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.infrastructure.prompt_context import PromptContext


def test_prompt_context_loads_and_persists_saved_source_mapping():
    async def scenario():
        saved = {"sources": {"S1": {"text": "original", "aliases": ["user_request"]}}, "knowledge": {}}
        writer = SimpleNamespace(exists=AsyncMock(return_value=True), read_json=AsyncMock(return_value=saved),
                                 write_json=AsyncMock())
        context = await PromptContext.create(writer)
        assert context.data["sources"]["S1"]["text"] == "original"
        await context.persist()
        writer.write_json.assert_awaited_once()
    asyncio.run(scenario())
