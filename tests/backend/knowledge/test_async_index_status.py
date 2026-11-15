"""projection 후에도 벡터 반영 대기와 실패를 표시한다."""

import asyncio
from contextlib import asynccontextmanager

import pytest

from backend.knowledge.projection_queue import projection_status


@pytest.mark.parametrize("embedding,expected", [({"pending": 1, "failed": 0}, "pending"), ({"pending": 0, "failed": 1}, "failed")])
def test_index_is_not_ready_until_embeddings_are_saved(embedding, expected):
    class Cursor:
        def __init__(self, row):
            self.row = row

        async def fetchone(self):
            return self.row

    class Connection:
        async def execute(self, sql, params):
            if "FROM projection_queue" in sql:
                return Cursor({"source": 2, "applied": 2, "pending": 0, "failed": 0})
            return Cursor(embedding)

    class Store:
        @asynccontextmanager
        async def transaction(self, *, mode):
            yield Connection()

    async def run():
        result = await projection_status(Store(), "job")
        assert result["index_status"] == expected

    asyncio.run(run())
