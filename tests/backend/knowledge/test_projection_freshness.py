"""벡터 지연과 검색용 원본 projection의 최신성은 서로 독립적이다."""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.knowledge.impact import impact_context
from backend.knowledge.runtime import KnowledgeService


@pytest.mark.parametrize("embedding_status", ["pending", "failed"])
@pytest.mark.parametrize("consumer", ["retrieval", "impact"])
def test_fresh_text_projection_supports_retrieval_and_impact_while_embedding_delayed(async_store_factory, embedding_status, consumer):
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project("projection fixture")
            job = {"id": "job", "project_id": project["id"], "request": "요청", "status": "FINALIZED"}
            await store.save_job(job)
            await store.documents("job").write_text("final/FINAL_AGENT_SPEC.md", "현재 승인 문서")
            async with store.transaction() as conn:
                await store.enqueue_stage(job, "execution", "requirement_lock", {"user_request": "요청"}, {}, connection=conn)
            assert await store.process_projection()
            async with store.transaction() as conn:
                await conn.execute(
                    "INSERT INTO nodes(id,content_id,job_id,logical_key,kind,body,attrs) "
                    "VALUES ('req','content','job','req-key','requirement','요구사항',%s::jsonb)",
                    ('{"scope":"product","requirement_id":"R1"}',),
                )
                await conn.execute("INSERT INTO embedding_queue(node_id,status) VALUES ('req',%s)", (embedding_status,))

            status = await store.projection_status("job")
            assert status["index_status"] == embedding_status
            assert status["index_source_revision"] == status["index_applied_revision"]
            store.state = AsyncMock(return_value={"status": "FINALIZED", "requirement_lock_sheet": {
                "mandatory_requirements": [{"id": "R1", "text": "요구사항"}],
            }})
            service = KnowledgeService(store, embedder=SimpleNamespace(close=lambda: None))
            service.search = AsyncMock(return_value={"mode": "text", "nodes": [{"id": "req", "job_id": "job"}]})
            try:
                if consumer == "retrieval":
                    assert [node["id"] for node in (await service.context("요구사항", project_id=project["id"]))["nodes"]] == ["req"]
                else:
                    result = await impact_context(store, "job", "req")
                    assert result["node"]["id"] == "req"
                    assert result["basis"]["status"] == "FINALIZED"
            finally:
                await service.close()

    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(scenario())


def test_failed_older_projection_blocks_reuse_even_when_max_revisions_match(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            project = await store.create_project("projection ordering fixture")
            job = {"id": "job", "project_id": project["id"], "request": "요청", "status": "FINALIZED"}
            await store.save_job(job)
            async with store.transaction() as conn:
                await store.enqueue_stage(job, "execution", "requirement_lock", {"user_request": "first"}, {}, connection=conn)
                await store.enqueue_stage(job, "execution", "requirement_lock", {"user_request": "second"}, {}, connection=conn)
                await conn.execute("UPDATE projection_queue SET status=CASE WHEN state->>'user_request'='first' "
                                   "THEN 'failed' ELSE 'completed' END WHERE job_id='job'")
            status = await store.projection_status("job")
            assert status["index_source_revision"] == status["index_applied_revision"]
            assert not await store.projection_ready("job")
            service = KnowledgeService(store, embedder=SimpleNamespace(close=lambda: None))
            service.search = AsyncMock(return_value={"mode": "text", "nodes": [{"id": "req", "job_id": "job"}]})
            try:
                assert (await service.context("요청", project_id=project["id"]))["nodes"] == []
                with pytest.raises(ValueError, match="검색 데이터 반영 중"):
                    await impact_context(store, "job", "req")
            finally:
                await service.close()

    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        runner.run(scenario())
