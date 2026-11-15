"""명시적으로 지정한 가짜 데이터 전용 DB에서 네이티브 비동기 I/O를 확인한다."""

import asyncio
import os
import sys
from uuid import uuid4

import pytest

from backend.knowledge.config import KnowledgeConfig, KnowledgeError
from backend.knowledge.store import KnowledgeStore


def test_native_database_wait_keeps_loop_responsive_and_failed_write_rolls_back():
    port = os.environ.get("TEST_ASYNC_DATABASE_PORT")
    if not port:
        pytest.skip("TEST_ASYNC_DATABASE_PORT로 가짜 데이터 전용 DB를 지정해야 합니다.")

    async def scenario():
        store = KnowledgeStore(KnowledgeConfig({
            "host": "127.0.0.1", "port": int(port), "dbname": "postgres",
            "user": "ci_service", "password": "ci-only", "sslmode": "disable",
        }))
        name = "async_fixture_" + uuid4().hex
        stop = asyncio.Event()
        beats = []

        async def heartbeat():
            while not stop.is_set():
                beats.append(True)
                await asyncio.sleep(0.005)

        pulse = asyncio.create_task(heartbeat())
        created = False
        try:
            async with store.transaction() as conn:
                await conn.execute(f"CREATE TABLE public.{name}(value integer)")
            created = True
            before = len(beats)
            async with store.transaction(mode="read") as conn:
                await conn.execute("SELECT pg_sleep(0.1)")
            assert len(beats) - before >= 3

            with pytest.raises(KnowledgeError):
                async with store.transaction() as conn:
                    await conn.execute(f"INSERT INTO public.{name} VALUES (7)")
                    await conn.execute("SELECT 1/0")
            async with store.transaction(mode="read") as conn:
                cursor = await conn.execute(f"SELECT count(*) AS total FROM public.{name}")
                assert (await cursor.fetchone())["total"] == 0
        finally:
            try:
                if created:
                    async with store.transaction() as conn:
                        await conn.execute(f"DROP TABLE public.{name}")
            finally:
                stop.set()
                await pulse
                await store.close_async()

    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(scenario())
