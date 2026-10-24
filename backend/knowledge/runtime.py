"""검색 서비스와 명시적으로 전달하는 작업 실행 문맥."""

from concurrent.futures import ThreadPoolExecutor
import threading
import json
from backend.knowledge.config import KnowledgeError
from backend.knowledge.embedding import LocalEmbedding


class KnowledgeService:
    def __init__(self, store, embedder=None):
        self.store = store
        self.embedder = embedder or LocalEmbedding(
            store.config.model_path, store.config.device
        )
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="embedding"
        )
        self.lock = threading.Lock()
        self.future = None
        self.running = False
        self.requested = False
        self.closed = False
        self.last_error = None

    def schedule(self):
        if getattr(self, "public_mode", False):
            return  # 공개 서비스의 색인은 독점 운영 작업에서 명시적으로 실행한다.
        with self.lock:
            if self.closed:
                return
            self.requested = True
            if not self.running:
                self.running = True
                self.future = self.executor.submit(self._worker)

    def _worker(self):
        while True:
            with self.lock:
                if self.closed or not self.requested:
                    self.running = False
                    return
                self.requested = False
            if not self.reindex():
                with self.lock:
                    if not self.requested or self.closed:
                        self.running = False
                        return

    def close(self):
        with self.lock:
            self.closed = True
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.embedder.close()

    def reindex(self):
        try:
            info = self.embedder.info()
            self.store.register_model(info)
            while True:
                if self.closed:
                    return False
                rows = self.store.pending_embeddings(info["id"])
                if not rows:
                    if self.store.activate_model(info["id"]):
                        break
                    continue
                for row in rows:
                    count = 0
                    for chunk in self.embedder.chunks(row):
                        if self.closed:
                            return False
                        vector = self.store.chunk_vector(chunk, info["id"])
                        if vector is None:
                            vector = self.embedder.encode([chunk["input"]])[0]
                        self.store.save_chunk(info, chunk, vector)
                        count += 1
                    self.store.complete_chunks(row["id"], info["id"], count)
            self.last_error = None
            return True
        except Exception:
            self.last_error = "청크 임베딩이 준비되지 않았습니다. 텍스트 검색을 사용합니다. 모델 경로·CPU 설정·다른 실행 여부를 확인하고 재시도하세요."
            try:
                self.store.embedding_failure()
            except KnowledgeError:
                pass
            return False

    def search(self, query, project_id=None, kind=None, status=None, job_id=None):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 20000:
            raise ValueError("검색어는 1~20000자로 입력하세요.")
        vector, model_id = None, None
        text_only = kind in {"input", "review"}
        if not text_only:
            try:
                active = self.store.active_model()
                info = (
                    self.embedder.info()
                    if getattr(self.embedder, "model", None) is not None
                    else None
                )
                if active and info and active["id"] == info["id"]:
                    vector = self.embedder.encode([query], query=True)[0]
                    model_id = info["id"]
            except Exception:
                pass
        result = self.store.search(
            query,
            project_id=project_id,
            kind=kind,
            status=status,
            vector=vector,
            model_id=model_id,
            **({"job_id": job_id} if job_id else {}),
        )
        result["embedding_status"] = (
            "not_applicable"
            if text_only
            else "ready"
            if vector is not None
            else "pending"
        )
        result["message"] = self.last_error if vector is None else None
        return result

    def context(self, query, project_id=None):
        result = self.search(query, project_id=project_id)
        nodes = {node["id"]: node for node in result["nodes"]}
        edges = {}
        for node in result["nodes"]:
            remaining = 60 - len(nodes)
            if remaining <= 0:
                break
            graph = self.store.graph(
                node_id=node["id"],
                project_id=project_id,
                depth=2,
                limit=min(remaining + 1, 60),
            )
            for neighbour in graph["nodes"]:
                if neighbour["id"] in nodes or len(nodes) < 60:
                    nodes[neighbour["id"]] = neighbour
            edges.update({edge["id"]: edge for edge in graph["edges"]})
        # 프롬프트 크기를 제한하면서 근거와 적용 조건도 포함한다.
        payload = {"nodes": [], "edges": [], "mode": result["mode"]}
        records = self.store.node_records(nodes) if nodes else {}
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
        self.retrieved = {"nodes": [], "edges": [], "mode": "text"}
        self.initial_sources = dict(documents.state.get("confirmed_user_sources", {}))
        from backend.knowledge.trace import action_sources

        self.user_sources = action_sources(service.store.action_records(job["id"]))

    def refresh(self, query):
        self.retrieved = self.service.context(
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

    def commit(self, stage, state):
        if stage not in {
            "requirement_lock",
            "spec_compile",
            "checklist_critic",
            "review_resolution",
            "approve",
        }:
            return
        self.service.store.commit_stage(
            self.job, self.job["execution_id"], stage, state, self.documents.all()
        )
        self.service.schedule()
