"""작업 실행의 저장·검색 문맥. 임베딩 실패와 DB 실패를 구분한다."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
import json
import re
from pathlib import Path
import threading
from uuid import uuid4

from backend.knowledge.config import KnowledgeError
from backend.knowledge.embedding import LocalEmbedding


CURRENT = ContextVar("knowledge_runtime", default=None)
ARTIFACT_PATHS = (
    "raw/user_request.md", "raw/web_feedback.md", "raw/revision_feedback.md", "state/state.json",
    "state/execution_history.json", "state/provider_usage.json",
    "state/conversation_state.json", "state/prompt_references.json",
    "state/private_model_assignments.json",
    "context/project_manifest.json", "context/project_summary.ko.md",
    "analysis/requirement_lock_sheet.json", "analysis/requirement_lock_sheet.ko.md",
    "analysis/spec_trace.json", "review/checklist_issues.json", "review/resolution.json", "review/resolved_draft.en.md",
    "analysis/01_intent_parse.ko.md", "analysis/02_requirement_lock.ko.md",
    "analysis/03_scope_classification.ko.md", "analysis/04_initial_assumptions.ko.md",
    "analysis/05_blocking_questions.ko.md", "research/web_sources.json",
    "research/web_research_summary.ko.md",
    "evidence/evidence_registry.json", "draft/approval_candidate_spec.en.md",
    "final/FINAL_AGENT_SPEC.md", "critical/CRITICAL_REPORT.ko.md", "critical/FAILED_AGENT_SPEC_DRAFT.en.md",
)


def is_artifact_path(relative):
    return (relative in ARTIFACT_PATHS
            or re.fullmatch(r"completed/[0-9a-f]{64}\.json", relative) is not None
            or re.fullmatch(r"history/[0-9a-f]{32}\.md", relative) is not None
            or re.fullmatch(r"translations/[0-9a-f]{64}/(?:translation\.ko\.json|validation\.json|state/(?:provider_usage|conversation_state)\.json)", relative) is not None)


def read_artifacts(root):
    root = Path(root).resolve()
    result = {}
    paths = list(ARTIFACT_PATHS)
    completed_dir = root / "completed"
    if completed_dir.is_dir() and not any(p.is_symlink() for p in (completed_dir, *completed_dir.parents)):
        paths.extend("completed/" + p.name for p in completed_dir.iterdir()
                     if not p.is_symlink() and re.fullmatch(r"[0-9a-f]{64}\.json", p.name))
    history_path = root / "state/execution_history.json"
    if history_path.is_file() and not any(parent.is_symlink() for parent in (history_path, *history_path.parents)):
        history = json.loads(history_path.read_text(encoding="utf-8"))
        for node in history.get("nodes", []):
            reference = node.get("detail", {}).get("document", {}).get("ref")
            if isinstance(reference, str) and re.fullmatch(r"history/[0-9a-f]{32}\.md", reference):
                paths.append(reference)
    translation_dir = root / "translations"
    if translation_dir.is_dir() and not any(parent.is_symlink() for parent in (translation_dir, *translation_dir.parents)):
        for folder in translation_dir.iterdir():
            if folder.is_dir() and not folder.is_symlink() and re.fullmatch(r"[0-9a-f]{64}", folder.name):
                paths.extend("translations/" + folder.name + "/" + name for name in
                             ("translation.ko.json", "validation.json", "state/provider_usage.json", "state/conversation_state.json"))
    for relative in dict.fromkeys(paths):
        path = root / relative
        # 신뢰된 파일명도 심볼릭 링크를 통해 다른 자료를 읽지 않게 한다.
        if any(parent.is_symlink() for parent in (path, *path.parents) if parent != root.parent):
            continue
        if path.is_file() and path.resolve().is_relative_to(root):
            result[relative] = path.read_text(encoding="utf-8")
    return result


def restore_artifacts(root, artifacts, *, reconcile=False):
    from backend.infrastructure.artifact_writer import ArtifactWriter
    writer = ArtifactWriter(root, allow_overwrite=True)

    def export(relative, content):
        target = writer.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(target)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    artifacts = dict(artifacts)
    if "state/state.json" in artifacts:
        state = json.loads(artifacts["state/state.json"])
        if state.get("run_id") or "output_dir" in state:
            state["output_dir"] = str(writer.output_dir)
        internal = {"approval_candidate_spec": "draft/approval_candidate_spec.en.md", "final_agent_spec": "final/FINAL_AGENT_SPEC.md",
                    "critical_report": "critical/CRITICAL_REPORT.ko.md", "evidence_registry_path": "evidence/evidence_registry.json",
                    "project_manifest_path": "context/project_manifest.json", "web_sources_path": "research/web_sources.json"}
        for field, relative in internal.items():
            if state.get(field):
                state[field] = str(writer.path(relative))
        artifacts["state/state.json"] = json.dumps(state, ensure_ascii=False)
    if reconcile:
        from backend.knowledge.projection import digest
        # 커밋되지 않은 내보내기는 별도로 보존한 뒤 캐시에서 분리한다.
        for relative, content in read_artifacts(root).items():
            if artifacts.get(relative) == content:
                continue
            backup = writer.path("state/recovery_exports/" + digest(content) + "/" + relative)
            if any(parent.is_symlink() for parent in (backup, *backup.parents)):
                raise KnowledgeError("작업 복원 경로가 올바르지 않습니다.")
            export(backup.relative_to(writer.output_dir).as_posix(), content)
            if relative not in artifacts and not relative.startswith("raw/"):
                writer.path(relative).unlink()
    for relative, content in artifacts.items():
        if not is_artifact_path(relative):
            continue
        target = writer.path(relative)
        if target.is_symlink() or any(parent.is_symlink() for parent in target.parents):
            raise KnowledgeError("작업 복원 경로가 올바르지 않습니다.")
        export(relative, content)


class KnowledgeService:
    def __init__(self, store, embedder=None):
        self.store = store
        self.embedder = embedder or LocalEmbedding(store.config.model_path, store.config.device)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="embedding")
        self.lock = threading.Lock()
        self.future = None
        self.running = False
        self.requested = False
        self.closed = False
        self.last_error = None

    def schedule(self):
        if getattr(self,'public_mode',False):
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
                info = self.embedder.info() if getattr(self.embedder, "model", None) is not None else None
                if active and info and active["id"] == info["id"]:
                    vector = self.embedder.encode([query], query=True)[0]
                    model_id = info["id"]
            except Exception:
                pass
        result = self.store.search(query, project_id=project_id, kind=kind, status=status, vector=vector, model_id=model_id, **({"job_id": job_id} if job_id else {}))
        result["embedding_status"] = "not_applicable" if text_only else "ready" if vector is not None else "pending"
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
            graph = self.store.graph(node_id=node["id"], project_id=project_id, depth=2, limit=min(remaining+1, 60))
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
            if detail["kind"] not in {"decision", "requirement", "spec"} or detail["attrs"].get("scope") != "product":
                continue
            bounded = {key: detail[key] for key in ("id", "project_id", "job_id", "kind", "active")}
            matches = nodes[node["id"]].get("matches", [])
            bounded["body"] = "\n\n".join(match["quote"] for match in matches) if matches else detail["body"][:1400]
            if matches:
                bounded["matches"] = [{"chunk_id": match["chunk_id"], "source_ranges": match["source_ranges"]} for match in matches]
            bounded["attrs"] = {key: value[:700] for key, value in detail["attrs"].items()
                                if key in {"actor", "status", "section", "requirement_id", "rationale", "conditions", "original_text", "origin", "scope"}
                                and isinstance(value, str)}
            payload["nodes"].append(bounded)
            if len(json.dumps(payload, ensure_ascii=False)) > 40000:
                payload["nodes"].pop()
                break
        kept = {node["id"] for node in payload["nodes"]}
        for edge in edges.values():
            if edge["source"] not in kept or edge["target"] not in kept:
                continue
            payload["edges"].append(edge)
            if len(payload["edges"]) > 200 or len(json.dumps(payload, ensure_ascii=False)) > 40000:
                payload["edges"].pop()
                break
        return payload


class RunKnowledge:
    def __init__(self, service, job, root):
        self.service = service
        self.job = job
        self.root = root
        self.retrieved = {"nodes": [], "edges": [], "mode": "text"}
        artifacts = read_artifacts(root)
        state = json.loads(artifacts.get("state/state.json", "{}"))
        self.initial_sources = dict(state.get("confirmed_user_sources", {}))
        if state.get("revision_feedback"):
            self.initial_sources["user_feedback"] = state["revision_feedback"]
        from backend.knowledge.trace import confirmed_sources, action_sources
        self.user_sources = {**confirmed_sources(state, artifacts), **action_sources(service.store.action_records(job["id"]))}
        self.persisted_history = set()
        self.resolved_draft_hash = None

    def refresh(self, query):
        self.retrieved = self.service.context(query, project_id=self.job.get("project_id"))

    def confirmed_sources(self, state):
        from backend.knowledge.trace import confirmed_sources
        return {**confirmed_sources(state, {}), **self.user_sources}

    def reusable_ids(self):
        return {node["id"] for node in self.retrieved["nodes"] if node.get("active") and node.get("attrs", {}).get("scope") == "product" and node.get("kind") in {"decision", "requirement", "spec"}}

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
                if item["actor"] == "user" and (value is None or item["text"] not in value):
                    value = next((text for key, text in reversed(list(current.items()))
                                  if key.startswith(source + ":") and item["text"] in text), value)
                versioned = source_version(source, value) if value is not None else source
                sources.append(versioned if versioned in current else source)
            item["sources"] = sources
        return bound

    def commit(self, stage, state, result=None):
        merged = {**state, **(result or {})}
        artifacts = read_artifacts(self.root)
        # 파일 이력이 누락되어도 접수 트랜잭션의 사용자 원문을 기준으로 판별한다.
        merged["confirmed_user_sources"] = self.confirmed_sources(merged)
        if "state/state.json" in artifacts:
            disk_state = json.loads(artifacts["state/state.json"])
            merged = {**disk_state, **merged}
        # 복원 시 파일과 DB가 서로 다른 단계의 상태를 가리키지 않게 한다.
        if merged.get("run_id"):
            artifacts["state/state.json"] = json.dumps(merged, ensure_ascii=False)
        if stage == "state" and merged.get("status") == "FINALIZED" and self.job.get("action") == "approve":
            stage = "approve"
        buffered = None
        if stage in {"project_context", "web_research", "interview", "await_user", "requirement_lock",
                     "spec_compile", "checklist_critic", "review_resolution", "compose_candidate", "critical_report", "approve"}:
            buffered = stage_history(self.root, artifacts, self.job["execution_id"], stage, merged)
            artifacts.update(buffered)
        self.service.store.commit_stage(self.job, self.job["execution_id"], stage, merged, artifacts)
        if stage == "review_resolution" and merged.get("resolution_history"):
            self.resolved_draft_hash = merged["resolution_history"][-1]["draft_hash"]
        if buffered is not None:
            restore_artifacts(self.root, buffered)
            self.persisted_history.add(stage)
        self.service.schedule()
        if stage == "requirement_lock":
            sheet = merged.get("requirement_lock_sheet", {})
            query = " ".join(item["text"] for item in sheet.get("mandatory_requirements", []))
            if query:
                self.refresh(query[:20000])


def stage_history(root, artifacts, execution_id, stage, state):
    """단계 상세와 문서 사본을 메모리에서 준비해 결과와 같은 트랜잭션에 넣는다."""
    from copy import deepcopy
    from backend.server.execution_history import ExecutionHistory

    class BufferedHistory(ExecutionHistory):
        def __init__(self):
            super().__init__(Path(root))
            self.data = json.loads(artifacts.get("state/execution_history.json", '{"version":1,"nodes":[],"executions":[]}'))
            self.documents = {}

        def _load(self, *, read_only=False):
            return deepcopy(self.data)

        def _save(self, data):
            self.data = deepcopy(data)

        def _copy_document(self, source, detail, node, kind):
            relative = source.relative_to(self.root).as_posix()
            if relative not in artifacts:
                node["detail_available"] = False
                return
            reference = f"history/{node['id']}.md"
            self.documents[reference] = artifacts[relative]
            detail["document"] = {"ref": reference, "filename": source.name, "kind": kind}
            node["has_document"] = True

    history = BufferedHistory()
    result = {key: state[key] for key in ("status", "blocking_questions", "structured_issues", "critic_pass_count",
              "request_type", "awaiting_input_reason", "review_questions", "resolution_history", "diagnosed_keys") if key in state}
    history.stage(execution_id, stage, "completed", result=result)
    history.capture(execution_id, stage, root=Path(root))
    return {"state/execution_history.json": json.dumps(history.data, ensure_ascii=False), **history.documents}


