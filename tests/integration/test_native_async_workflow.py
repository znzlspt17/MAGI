"""실제 PostgreSQL wire와 가짜 모델을 통과하는 워크플로."""

import asyncio

from backend.engine import Engine
from backend.knowledge.runtime import KnowledgeService
from backend.server.job_manager import JobManager
from tests.backend.application.async_helpers import run_async
from tests.support.fakes import DecisionProvider


@run_async
async def test_real_workflow_with_fake_provider_uses_async_database(async_store_factory):
    async with async_store_factory() as store:
        provider = DecisionProvider([[], [], [], []])
        knowledge = KnowledgeService(store)
        # 모델 미설치 환경에서도 이 테스트는 workflow와 DB 경계를 검증한다.
        knowledge.schedule = lambda: None
        manager = await JobManager.build(
            knowledge, engine_factory=lambda docs, runtime: Engine(docs, runtime, provider=provider)
        )
        try:
            job = await manager.create("Windows에서 로컬 메모를 저장하는 프로그램")
            pending = list(manager._futures)
            assert len(pending) == 1
            await pending[0]
            assert manager.jobs[job["id"]]["status"] == "PASS_PENDING_USER_APPROVAL"
            assert provider.calls, "워크플로가 가짜 모델을 실제로 호출해야 합니다"
            assert (await store.documents(job["id"]).read_text("raw/user_request.md"))
            current = await manager.workspace.public(job["id"])
            assert current["state"]["candidate_hash"]
            updated = await manager.action(job["id"], "approve",
                {"candidate_hash": current["state"]["candidate_hash"]},
                expected_execution_id=job["execution_id"])
            assert updated["status"] == "queued"
            await next(iter(manager._futures))
            assert manager.jobs[job["id"]]["status"] == "FINALIZED"
            assert (await store.documents(job["id"]).read_text("final/FINAL_AGENT_SPEC.md"))
        finally:
            await manager.close()


@run_async
async def test_completed_workflow_is_indexed_in_background(async_store_factory):
    class Embedder:
        model = object()
        model_id = "fixture-model"
        def info(self):
            return {"id": self.model_id, "dimensions": 2, "max_length": 512}
        def chunks(self, row):
            yield {"id": "chunk-" + row["id"], "node_id": row["id"], "ordinal": 0,
                   "rule": "fixture", "title_path": "", "body": row["body"],
                   "input": row["body"], "input_hash": row["id"],
                   "source_ranges": [{"field": "body", "start": 0, "end": len(row["body"])}]}
        def encode(self, texts, *, query=False):
            return [[1.0, 0.0] for _ in texts]
        def close(self):
            pass

    async with async_store_factory() as store:
        knowledge = KnowledgeService(store, Embedder())
        provider = DecisionProvider([[], [], [], []])
        manager = await JobManager.build(
            knowledge, engine_factory=lambda docs, runtime: Engine(docs, runtime, provider=provider)
        )
        knowledge.start_background()
        try:
            job = await manager.create("Windows에서 로컬 메모를 저장하는 프로그램")
            await next(iter(manager._futures))
            assert manager.jobs[job["id"]]["status"] == "PASS_PENDING_USER_APPROVAL"
            async def ready():
                while (await store.projection_status(job["id"]))["index_status"] != "ready":
                    await asyncio.sleep(.05)
            await asyncio.wait_for(ready(), timeout=20)
            async with store.transaction(mode="read") as conn:
                row = await (await conn.execute("SELECT count(*) AS total FROM chunk_vectors")).fetchone()
                assert row["total"] > 0
        finally:
            await manager.close()
