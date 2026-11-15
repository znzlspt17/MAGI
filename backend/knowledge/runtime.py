"""검색 서비스와 명시적으로 전달하는 작업 실행 문맥."""
from typing import Any

from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from contextvars import copy_context
from functools import partial
import asyncio
import json
from backend.access.context import ACTOR
from backend.knowledge.store import ASYNC_TRANSACTION
from backend.knowledge.config import KnowledgeError
from backend.knowledge.embedding import LocalEmbedding


INDEX_STAGES = frozenset({'input', 'requirement_lock', 'spec_compile', 'checklist_critic',
                          'review_resolution', 'compose_candidate', 'approve'})


def index_stage(stage):
    return 'requirement_lock' if stage == 'requirement_lock_stage' else stage


class KnowledgeService:
    def __init__(self, store, embedder=None):
        self.store = store
        self.embedder = embedder or LocalEmbedding(store.config.model_path, store.config.device)
        # 2026-11-13: 하나의 모델만 메모리에 올리고 CPU 작업은 이벤트 루프 밖에서 실행한다.
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="embedding")
        self.closed = False
        self.last_error = None
        self.projection_error = None
        self._projection_wake = asyncio.Event()
        self._embedding_wake = asyncio.Event()
        self._projection_task = None
        self._embedding_task = None
        self._query_tasks = {}
        self._query_cache = OrderedDict()

    @staticmethod
    def _background_context():
        # 2026-11-13: 백그라운드 작업이 요청의 인증이나 열린 트랜잭션을 상속하지 않는다.
        context = copy_context()
        context.run(ACTOR.set, None)
        context.run(ASYNC_TRANSACTION.set, None)
        return context

    def start_background(self):
        if self.closed:
            return
        loop = asyncio.get_running_loop()
        if self._projection_task is None or self._projection_task.done():
            self._projection_task = loop.create_task(self._projection_worker(), context=self._background_context())
        if self._embedding_task is None or self._embedding_task.done():
            self._embedding_task = loop.create_task(self._worker(), context=self._background_context())

    def schedule(self):
        if not self.closed:
            self.start_background()
            self._projection_wake.set()
            self._embedding_wake.set()

    @staticmethod
    async def _wait(wake):
        try:
            await asyncio.wait_for(wake.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
        wake.clear()

    async def _projection_worker(self):
        while not self.closed:
            try:
                while not self.closed and await self.store.process_projection():
                    self._embedding_wake.set()
                self.projection_error = None
            except Exception:
                self.projection_error = "검색 데이터 반영을 잠시 완료하지 못했습니다. 다시 시도합니다."
            await self._wait(self._projection_wake)

    async def _worker(self):
        while not self.closed:
            await self.reindex()
            await self._wait(self._embedding_wake)

    async def close(self):
        self.closed = True
        tasks = [task for task in (self._projection_task, self._embedding_task) if task]
        tasks.extend(self._query_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.to_thread(self.executor.shutdown, wait=True, cancel_futures=True)
        await asyncio.to_thread(self.embedder.close)

    async def reindex(self):
        node_id = None
        initializing = True
        loop = asyncio.get_running_loop()
        try:
            info = await loop.run_in_executor(self.executor, self.embedder.info)
            initializing = False
            await self.store.register_model(info)
            while not self.closed:
                rows = await self.store.pending_embeddings(info["id"])
                if not rows:
                    await self.store.activate_model(info["id"])
                    break
                for row in rows:
                    node_id = row["id"]
                    chunks = await loop.run_in_executor(self.executor, lambda: list(self.embedder.chunks(row)))
                    count = 0
                    for chunk in chunks:
                        if self.closed:
                            return False
                        vector = await self.store.chunk_vector(chunk, info["id"])
                        if vector is None:
                            vector = (await loop.run_in_executor(self.executor, self.embedder.encode, [chunk["input"]]))[0]
                        await self.store.save_chunk(info, chunk, vector)
                        count += 1
                    await self.store.complete_chunks(node_id, info["id"], count)
                    node_id = None
            self.last_error = None
            return True
        except asyncio.CancelledError:
            raise
        except Exception:
            self.last_error = "청크 임베딩이 준비되지 않았습니다. 텍스트 검색을 사용합니다. 모델 경로·CPU 설정·다른 실행 여부를 확인하고 재시도하세요."
            if node_id:
                try:
                    await self.store.embedding_failure(node_id)
                except KnowledgeError:
                    pass
            elif initializing:
                try:
                    await self.store.embedding_initialization_failure()
                except KnowledgeError:
                    pass
            return False

    def _schedule_query(self, key, query):
        if self.closed or key in self._query_tasks or len(self._query_tasks) >= 128:
            return
        async def compute():
            try:
                loop = asyncio.get_running_loop()
                values = await loop.run_in_executor(self.executor, partial(self.embedder.encode, [query], query=True))
                self._query_cache[key] = values[0]
                self._query_cache.move_to_end(key)
                while len(self._query_cache) > 128:
                    self._query_cache.popitem(last=False)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            finally:
                self._query_tasks.pop(key, None)
        self._query_tasks[key] = asyncio.create_task(compute(), context=self._background_context())

    async def search(self, query, project_id=None, kind=None, status=None, job_id=None):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 20000:
            raise ValueError("검색어는 1~20000자로 입력하세요.")
        vector, model_id = None, None
        text_only = kind in {"input", "review"}
        if not text_only:
            active = await self.store.active_model()
            info_id = getattr(self.embedder, "model_id", None)
            if active and getattr(self.embedder, "model", None) is not None and active["id"] == info_id:
                actor = ACTOR.get()
                scope = tuple(sorted(actor.get("owner_ids", [actor["id"]]))) if actor else ("local",)
                key = (scope, info_id, query)
                vector = self._query_cache.get(key)
                if vector is None:
                    self._schedule_query(key, query)
                else:
                    self._query_cache.move_to_end(key)
                    model_id = info_id
        result = await self.store.search(query, project_id=project_id, kind=kind, status=status,
                                         vector=vector, model_id=model_id, **({"job_id": job_id} if job_id else {}))
        result["embedding_status"] = "not_applicable" if text_only else "ready" if vector is not None else "pending"
        result["message"] = self.last_error if vector is None else None
        result.update(await self.store.projection_status(job_id, project_id=project_id))
        return result


    async def context(self, query, project_id=None):
        result = await self.search(query, project_id=project_id)
        # 2026-11-13: 이전 projection은 표시할 수 있지만 최신 근거로 재사용하지 않는다.
        readiness = {}
        async def reusable(node):
            job_id = node.get("job_id")
            if not job_id:
                return False
            if job_id not in readiness:
                readiness[job_id] = await self.store.projection_ready(job_id)
            return readiness[job_id]
        nodes = {node["id"]: node for node in result["nodes"] if await reusable(node)}
        edges = {}
        for node in list(nodes.values()):
            remaining = 60 - len(nodes)
            if remaining <= 0:
                break
            graph = await self.store.graph(
                node_id=node["id"],
                project_id=project_id,
                depth=2,
                limit=min(remaining + 1, 60),
            )
            for neighbour in graph["nodes"]:
                if await reusable(neighbour) and (neighbour["id"] in nodes or len(nodes) < 60):
                    nodes[neighbour["id"]] = neighbour
            edges.update({edge["id"]: edge for edge in graph["edges"]})
        # 프롬프트 크기를 제한하면서 근거와 적용 조건도 포함한다.
        payload = {"nodes": [], "edges": [], "mode": result["mode"]}
        records = await self.store.node_records(nodes) if nodes else {}
        for node in list(nodes.values())[:60]:
            detail = records.get(node["id"])
            if detail is None:
                continue  # 조회 사이에 정리된 출처는 프롬프트로 재사용하지 않는다.
            if project_id and detail["project_id"] != project_id:
                continue
            if (
                detail["kind"] not in {"decision", "requirement", "spec"}
                or detail["attrs"].get("scope") != "product"
            ):
                continue
            bounded = {
                key: detail[key]
                for key in ("id", "project_id", "job_id", "kind", "active")
            }
            matches = nodes[node["id"]].get("matches", [])
            bounded["body"] = (
                "\n\n".join(match["quote"] for match in matches)
                if matches
                else detail["body"][:1400]
            )
            if matches:
                bounded["matches"] = [
                    {
                        "chunk_id": match["chunk_id"],
                        "source_ranges": match["source_ranges"],
                    }
                    for match in matches
                ]
            bounded["attrs"] = {
                key: value[:700]
                for key, value in detail["attrs"].items()
                if key
                in {
                    "actor",
                    "status",
                    "section",
                    "requirement_id",
                    "rationale",
                    "conditions",
                    "original_text",
                    "origin",
                    "scope",
                }
                and isinstance(value, str)
            }
            payload["nodes"].append(bounded)
            if len(json.dumps(payload, ensure_ascii=False)) > 40000:
                payload["nodes"].pop()
                break
        kept = {node["id"] for node in payload["nodes"]}
        for edge in edges.values():
            if edge["source"] not in kept or edge["target"] not in kept:
                continue
            payload["edges"].append(edge)
            if (
                len(payload["edges"]) > 200
                or len(json.dumps(payload, ensure_ascii=False)) > 40000
            ):
                payload["edges"].pop()
                break
        return payload


class RunKnowledge:
    def __init__(self, service, job, documents, *, meter=None):
        self.service, self.job, self.documents, self.meter = (
            service,
            job,
            documents,
            meter,
        )
        self.retrieved: dict[str, Any] = {"nodes": [], "edges": [], "mode": "text"}
        self.initial_sources = dict(documents.state.get("confirmed_user_sources", {}))
        self.user_sources = {}

    async def initialize(self):
        from backend.knowledge.trace import action_sources
        self.user_sources = action_sources(await self.service.store.action_records(self.job["id"]))
        return self

    async def refresh(self, query):
        self.retrieved = await self.service.context(
            query, project_id=self.job.get("project_id")
        )

    def confirmed_sources(self, state):
        from backend.knowledge.trace import confirmed_sources

        return {**self.initial_sources, **confirmed_sources(state), **self.user_sources}

    def reusable_ids(self):
        return {
            node["id"]
            for node in self.retrieved["nodes"]
            if node.get("job_id") == self.job["id"]
            and node.get("active")
            and node.get("attrs", {}).get("scope") == "product"
            and node.get("kind") in {"decision", "requirement", "spec"}
        }

    def bind_decisions(self, decisions, previous=()):
        from copy import deepcopy
        from backend.knowledge.trace import source_version

        current = self.confirmed_sources({})
        prior = {item["id"]: item for item in previous}
        bound = deepcopy(decisions)
        for item in bound:
            basis = self.initial_sources if prior.get(item["id"]) == item else current
            sources = []
            for source in item["sources"]:
                value = basis.get(source, current.get(source))
                # 사용자 인용의 원문 버전이 남아 있으면 최신 별칭에 다시 연결하지 않는다.
                if item["actor"] == "user" and (
                    value is None or item["text"] not in value
                ):
                    value = next(
                        (
                            text
                            for key, text in reversed(list(current.items()))
                            if key.startswith(source + ":") and item["text"] in text
                        ),
                        value,
                    )
                versioned = (
                    source_version(source, value) if value is not None else source
                )
                sources.append(versioned if versioned in current else source)
            item["sources"] = sources
        return bound

    async def commit(self, stage, state):
        stage = index_stage(stage)
        if stage not in INDEX_STAGES:
            return
        async with self.service.store.transaction() as conn:
            if self.meter is not None:
                meter = self.meter
                await meter.access.execution(conn, meter.uid, meter.jid, meter.generation, meter.execution_id)
            await self.service.store.enqueue_stage(
                self.job, self.job["execution_id"], stage, state, await self.documents.all(), connection=conn
            )
        self.service.schedule()
