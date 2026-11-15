"""테스트 전용 DB가 실제 psycopg 비동기 연결과 격리를 제공한다."""

import asyncio
import sys


def test_async_fixture_provides_migrated_isolated_store(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            async with store.transaction(mode="read") as conn:
                cursor = await conn.execute("SELECT to_regclass('public.users') AS users")
                assert (await cursor.fetchone())["users"] == "users"
        async with async_store_factory() as store:
            async with store.transaction(mode="read") as conn:
                cursor = await conn.execute("SELECT count(*) AS total FROM public.users")
                assert (await cursor.fetchone())["total"] == 0

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None) as runner:
        runner.run(scenario())
