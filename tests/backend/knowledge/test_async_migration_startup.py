"""빈 테스트 DB의 비동기 마이그레이션과 재시작 동작."""

import asyncio
import sys
from types import SimpleNamespace

from backend.knowledge.setup import load_migrations, migrate


def test_empty_database_is_initialized_once_and_reuses_migration_history(async_store_factory):
    async def scenario():
        async with async_store_factory(initialized=False) as store:
            runtime = SimpleNamespace(store=store, connection=object())
            first = await migrate(store, runtime=runtime)
            assert first["phase"] == "ready"
            assert first["applied"] == len(load_migrations())
            assert (await migrate(store, runtime=runtime))["applied"] == 0
            await store.require_ready()

    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(scenario())
