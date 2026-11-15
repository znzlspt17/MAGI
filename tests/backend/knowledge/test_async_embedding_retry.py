"""임베딩 실패가 다른 원본의 색인을 방해하지 않는지 검증한다."""

import asyncio
import sys
from backend.knowledge.runtime import KnowledgeService


def test_failed_embedding_only_delays_its_own_source(async_store_factory):
    class Embedder:
        def info(self):
            return {"id": "fixture-model", "dimensions": 2, "max_length": 512}

        def chunks(self, row):
            yield {"id": "chunk-" + row["id"], "node_id": row["id"], "ordinal": 0,
                   "rule": "fixture", "title_path": "", "body": row["body"],
                   "input": row["body"], "input_hash": row["id"],
                   "source_ranges": [{"field": "body", "start": 0, "end": len(row["body"])}]}

        def encode(self, texts):
            if texts == ["bad"]:
                raise ValueError("fixture failure")
            return [[1.0, 0.0]]

        def close(self):
            pass

    async def scenario():
        async with async_store_factory() as store:
            async with store.transaction() as conn:
                await conn.execute("INSERT INTO projects(id,name) VALUES ('p','test')")
                await conn.execute("INSERT INTO jobs(id,project_id,data) VALUES ('j','p','{}'::jsonb)")
                for ident, body in [("a", "bad"), ("b", "good")]:
                    await conn.execute("INSERT INTO nodes(id,content_id,job_id,logical_key,kind,body,attrs) "
                                       "VALUES (%s,%s,'j',%s,'requirement',%s,%s::jsonb)",
                                       (ident, ident, ident, body, '{"scope":"product"}'))
                    await conn.execute("INSERT INTO embedding_queue(node_id) VALUES (%s)", (ident,))
            service = KnowledgeService(store, Embedder())
            try:
                assert not await service.reindex()
                await service.reindex()
                async with store.transaction(mode="read") as conn:
                    rows = await (await conn.execute("SELECT node_id,status,attempts FROM embedding_queue ORDER BY node_id")).fetchall()
                assert rows == [{"node_id": "a", "status": "failed", "attempts": 1},
                                {"node_id": "b", "status": "completed", "attempts": 0}]
            finally:
                await service.close()

    factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=factory) as runner:
        runner.run(scenario())


def test_model_initialization_failure_marks_pending_sources_and_recovers(async_store_factory):
    class Embedder:
        failed = True
        def info(self):
            if self.failed:
                raise ValueError('model unavailable')
            return {'id': 'fixture-model', 'dimensions': 2, 'max_length': 512}
        def chunks(self, row):
            yield {'id': 'chunk-' + row['id'], 'node_id': row['id'], 'ordinal': 0,
                   'rule': 'fixture', 'title_path': '', 'body': row['body'],
                   'input': row['body'], 'input_hash': row['id'], 'source_ranges': []}
        def encode(self, texts):
            return [[1.0, 0.0]]
        def close(self):
            pass

    async def scenario():
        async with async_store_factory() as store:
            async with store.transaction() as conn:
                await conn.execute("INSERT INTO projects(id,name) VALUES ('p','test')")
                await conn.execute("INSERT INTO jobs(id,project_id,data) VALUES ('j','p','{}'::jsonb)")
                await conn.execute("INSERT INTO nodes(id,content_id,job_id,logical_key,kind,body,attrs) VALUES ('a','a','j','a','requirement','body',%s::jsonb)", ('{"scope":"product"}',))
                await conn.execute("INSERT INTO embedding_queue(node_id) VALUES ('a')")
            embedder = Embedder()
            service = KnowledgeService(store, embedder)
            try:
                assert not await service.reindex()
                assert (await store.projection_status('j'))['index_status'] == 'failed'
                async with store.transaction(mode='read') as conn:
                    event = await (await conn.execute("SELECT payload FROM progress_outbox WHERE job_id='j' ORDER BY id DESC LIMIT 1")).fetchone()
                assert event['payload']['job']['index_status'] == 'failed'
                embedder.failed = False
                async with store.transaction() as conn:
                    await conn.execute('UPDATE embedding_queue SET next_attempt=0')
                assert await service.reindex()
                assert (await store.projection_status('j'))['index_status'] == 'ready'
                async with store.transaction(mode='read') as conn:
                    event = await (await conn.execute("SELECT payload FROM progress_outbox WHERE job_id='j' ORDER BY id DESC LIMIT 1")).fetchone()
                assert event['payload']['job']['index_status'] == 'ready'
            finally:
                await service.close()
    factory = asyncio.SelectorEventLoop if sys.platform == 'win32' else None
    with asyncio.Runner(loop_factory=factory) as runner:
        runner.run(scenario())
