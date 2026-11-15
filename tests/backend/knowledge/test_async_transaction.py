"""비동기 트랜잭션의 작업 단위 격리와 완료 경계."""

import asyncio
from contextvars import copy_context
from contextlib import asynccontextmanager

import pytest

from backend.knowledge.config import KnowledgeConfig, KnowledgeError
from backend.knowledge.store import ASYNC_TRANSACTION, KnowledgeStore


class FakeConnection:
    def __init__(self, pool):
        self.pool = pool
        self.statements = []

    async def execute(self, sql, params=()):
        self.statements.append((sql, params))

    @asynccontextmanager
    async def transaction(self):
        self.pool.open_transactions += 1
        try:
            yield
            if self.pool.fail_commit:
                raise RuntimeError("commit failed")
            self.pool.commits += 1
        except BaseException:
            self.pool.rollbacks += 1
            raise
        finally:
            self.pool.open_transactions -= 1


class FakePool:
    def __init__(self):
        self.connections = []
        self.open_transactions = 0
        self.commits = 0
        self.rollbacks = 0
        self.fail_commit = False

    @asynccontextmanager
    async def connection(self):
        conn = FakeConnection(self)
        self.connections.append(conn)
        yield conn


def test_transaction_keeps_event_loop_responsive_and_commits_before_return():
    async def scenario():
        store = KnowledgeStore(KnowledgeConfig({}))
        pool = FakePool()
        store._async_pool = pool
        started, resume = asyncio.Event(), asyncio.Event()

        async def slow_save():
            async with store.transaction() as conn:
                started.set()
                await resume.wait()
                await conn.execute("INSERT INTO fixture VALUES (1)")
            return pool.commits

        task = asyncio.create_task(slow_save())
        await asyncio.wait_for(started.wait(), timeout=1)
        assert not task.done()
        resume.set()
        assert await task == 1
        assert pool.open_transactions == 0

    asyncio.run(scenario())


def test_nested_transaction_reuses_only_own_task_connection():
    async def scenario():
        store = KnowledgeStore(KnowledgeConfig({}))
        pool = FakePool()
        store._async_pool = pool
        async with store.transaction(mode="read") as outer:
            async with store.transaction(mode="read") as nested:
                assert nested is outer

            async def child():
                async with store.transaction(mode="read") as conn:
                    assert conn is not outer

            # 부모 트랜잭션을 물려받은 자식은 독립 컨텍스트 없이 시작할 수 없다.
            with pytest.raises(KnowledgeError, match="다른 태스크"):
                await asyncio.create_task(child())
            context = copy_context()
            context.run(ASYNC_TRANSACTION.set, None)
            await asyncio.create_task(child(), context=context)
        assert len(pool.connections) == 2
        assert pool.commits == 2

    asyncio.run(scenario())


def test_commit_failure_and_cancel_do_not_report_success():
    async def scenario():
        store = KnowledgeStore(KnowledgeConfig({}))
        pool = FakePool()
        store._async_pool = pool
        pool.fail_commit = True
        with pytest.raises(KnowledgeError):
            async with store.transaction():
                pass
        assert pool.rollbacks == 1

        pool.fail_commit = False
        started = asyncio.Event()

        async def operation():
            async with store.transaction():
                started.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(operation())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert pool.rollbacks == 2
        assert pool.open_transactions == 0

    asyncio.run(scenario())


def test_workflows_receive_distinct_async_checkpointers_using_same_pool():
    from backend.knowledge.core import checkpoint_store
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async def scenario():
        store = KnowledgeStore(KnowledgeConfig({}))
        pool = FakePool()
        store._async_pool = pool
        async with checkpoint_store(store) as first:
            async with checkpoint_store(store) as second:
                assert isinstance(first, AsyncPostgresSaver)
                assert first is not second
                assert first.conn is pool and second.conn is pool
                assert not pool.connections

    asyncio.run(scenario())


def test_checkpoint_read_reuses_active_transaction_and_restores_search_path():
    from backend.knowledge.core import checkpoint_store

    async def scenario():
        store = KnowledgeStore(KnowledgeConfig({}))
        pool = FakePool()
        store._async_pool = pool
        async with store.transaction() as conn:
            async with checkpoint_store(store) as saver:
                assert saver.conn is conn
                assert conn.statements[-1][0] == "SET LOCAL search_path TO workflow, core, public"
            assert conn.statements[-1][0] == "SET LOCAL search_path TO core, public"
        assert len(pool.connections) == 1

    asyncio.run(scenario())
