"""검색어 임베딩이 요청과 다른 사용자 범위를 막지 않는지 확인한다."""

import asyncio
import threading

from backend.access.context import ACTOR
from backend.knowledge.runtime import KnowledgeService


class _Embedder:
    model = object()
    model_id = "test-model"

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def info(self):
        return {"id": "test-model", "dimensions": 2}

    def encode(self, texts, *, query=False):
        self.started.set()
        self.release.wait(2)
        return [[1.0, 0.0]]

    def close(self):
        pass


class _Store:
    async def active_model(self):
        return {"id": "test-model"}

    async def search(self, query, *, vector, **kwargs):
        return {"nodes": [], "mode": "hybrid" if vector else "text"}

    async def projection_status(self, *args, **kwargs):
        return {"index_status": "ready", "index_source_revision": 1, "index_applied_revision": 1}


def test_search_returns_text_while_query_vector_is_computed_in_background():
    async def scenario():
        embedder = _Embedder()
        service = KnowledgeService(_Store(), embedder)
        token = ACTOR.set({"id": "owner-a", "owner_ids": ["owner-a"]})
        try:
            first = await asyncio.wait_for(service.search("검색어"), timeout=0.5)
            assert first["mode"] == "text"
            assert first["embedding_status"] == "pending"
            embedder.release.set()
            for _ in range(100):
                await asyncio.sleep(0.01)
                second = await service.search("검색어")
                if second["mode"] == "hybrid":
                    break
            assert second["mode"] == "hybrid"

            other = ACTOR.set({"id": "owner-b", "owner_ids": ["owner-b"]})
            try:
                assert (await service.search("검색어"))["mode"] == "text"
            finally:
                ACTOR.reset(other)
        finally:
            embedder.release.set()
            ACTOR.reset(token)
            await service.close()

    asyncio.run(scenario())
