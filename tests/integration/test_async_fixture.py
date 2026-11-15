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


def test_isolated_pool_matches_database_connection_model(async_store_factory, monkeypatch):
    monkeypatch.delenv('CI_POSTGRES', raising=False)
    async def scenario():
        async with async_store_factory() as store:
            assert store._async_pool.max_size == 1
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop if sys.platform == 'win32' else None) as runner:
        runner.run(scenario())


def test_postgres_pool_retains_parallel_connections(async_store_factory):
    import os
    import pytest
    if os.environ.get('CI') != 'true' or os.environ.get('CI_POSTGRES') != '1':
        pytest.skip('실제 PostgreSQL 전용 검증')
    async def scenario():
        async with async_store_factory() as store:
            assert store._async_pool.max_size == 8
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop if sys.platform == 'win32' else None) as runner:
        runner.run(scenario())
