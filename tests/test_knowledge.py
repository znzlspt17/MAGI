"""실제 비밀 설정 없이 저장 경계·검색·모델 실패와 이관을 검증한다."""

from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from backend.knowledge.config import KnowledgeConfig, KnowledgeError
from backend.knowledge.embedding import LocalEmbedding
from backend.knowledge.projection import digest, project
from backend.knowledge.runtime import CURRENT, KnowledgeService, RunKnowledge, read_artifacts, restore_artifacts
from backend.knowledge.store import KnowledgeStore
from backend.knowledge.trace import validate_decisions, validate_links
from backend.knowledge.__main__ import import_legacy


def sheet():
    return {"workflow_constraints": [], "mandatory_requirements": [{"id": "REQ-001", "text": "Store notes offline.",
        "source": "user_answer:Q-1", "sources": ["user_answer:Q-1"]}],
        "user_answers": [{"question_id": "Q-1", "question": "저장 방식은?", "answer": "오프라인 저장"}]}


def decision(**overrides):
    return {"id": "DEC-001", "text": "Use local storage.", "actor": "llm", "rationale": "Offline is required.",
            "conditions": "Single device", "sources": ["user_answer:Q-1"], "requirement_ids": ["REQ-001"],
            "reused_node_ids": [], **overrides}


@pytest.mark.parametrize("change", [
    {"requirement_ids": ["REQ-MISSING"]}, {"sources": ["user_answer:MISSING"]},
    {"reused_node_ids": ["missing"]}, {"actor": "user"},
    {"reused_node_ids": ["known"], "rationale": ""},
])
def test_trace_rejects_unknown_and_fabricated_user_decisions(change):
    with pytest.raises(ValueError):
        validate_decisions([decision(**change)], sheet(), ["known"], request="메모 앱")


def test_trace_accepts_exact_user_quote_and_llm_reuse():
    validate_decisions([decision(actor="user", text="오프라인 저장")], sheet())
    validate_decisions([decision(reused_node_ids=["known"])], sheet(), ["known"])
    with pytest.raises(ValueError):
        validate_decisions([decision(), decision()], sheet())
    link = {"item_id": "ITEM-1", "section": "architecture", "quote": "Use files.",
            "requirement_ids": ["REQ-001"], "decision_ids": ["DEC-001"]}
    validate_links([link], [decision()], sheet(), {"architecture": "Use files."})
    with pytest.raises(ValueError):
        validate_links([{**link, "quote": "Invented quote"}], [decision()], sheet(), {"architecture": "Use files."})


def test_projection_versions_provenance_and_does_not_promote_approval():
    state = {"user_request": "메모 앱", "requirement_lock_sheet": sheet(), "user_approval_status": "APPROVED"}
    state["requirement_lock_sheet"]["decisions"] = [decision(reused_node_ids=["external"])]
    artifacts = {"draft/approval_candidate_spec.en.md": "## 13. Architecture\nUse files. REQ-001"}
    nodes, edges = project("a" * 32, state, artifacts)
    assert any(node["attrs"].get("actor") == "llm" and node["attrs"].get("status") == "proposed" for node in nodes)
    assert any(edge["source"] == "external" and edge["kind"] == "reused" for edge in edges)
    assert {"evidence", "derived", "implemented"} <= {edge["kind"] for edge in edges}
    changed = deepcopy(state)
    changed["requirement_lock_sheet"]["user_answers"][0]["answer"] = "온라인 저장"
    new_nodes, _ = project("a" * 32, changed, artifacts)
    old = next(node for node in nodes if node["logical_key"] == "user_answer:Q-1")
    new = next(node for node in new_nodes if node["logical_key"] == old["logical_key"])
    assert old["id"] != new["id"]
    assert project("a" * 32, state, artifacts) == (nodes, edges)
    assert not {node["id"] for node in nodes} & {node["id"] for node in project("b" * 32, state, artifacts)[0]}


def test_inferred_interview_answer_is_not_a_confirmed_user_decision():
    state = {"user_request": "메모 앱", "requirement_lock_sheet": sheet()}
    nodes, _ = project("job", state, {})
    answer = next(node for node in nodes if node["logical_key"] == "user_answer:Q-1")
    assert answer["attrs"]["actor"] == "llm"
    history = {"nodes": [{"action": "answer", "result": {"answers": sheet()["user_answers"]}}]}
    nodes, _ = project("job", state, {"state/execution_history.json": json.dumps(history)})
    answer = next(node for node in nodes if node["logical_key"] == "user_answer:Q-1")
    assert answer["attrs"]["actor"] == "user"
    with pytest.raises(ValueError):
        validate_decisions([decision(actor="user", text="오프라인 저장")], sheet(), confirmed={"user_request": "메모 앱"})


def test_real_workflow_context_commits_trace_and_approval_remains_separate(tmp_path, monkeypatch):
    from test_review_decisions import DecisionProvider, engine_for
    from backend.models import SpecDraftResponse as SpecResponse, SpecBlock
    from backend.server.job_manager import JobManager
    class Provider(DecisionProvider):
        def complete_result(self, messages, **kwargs):
            result = super().complete_result(messages, **kwargs)
            if isinstance(result.parsed, SpecResponse):
                from backend.knowledge.trace import SpecLink, DecisionTrace
                result.parsed.decisions = [DecisionTrace(**decision(sources=[], reused_node_ids=[]))]
                result.parsed.architecture = [SpecBlock(item_id="ITEM-001", text="Store notes locally.",
                                                   requirement_ids=["REQ-001"], decision_ids=["DEC-001"])]
            return result
    provider = Provider([[]])
    store = MemoryStore()
    service = KnowledgeService(store, LocalEmbedding(None))
    service.schedule = lambda: None
    manager = JobManager(tmp_path, engine_factory=lambda: engine_for(provider), knowledge=service)
    monkeypatch.setattr(manager, "_submit_locked", lambda *a: None)
    try:
        job = manager.create("메모 앱")
        manager._run(job["id"], "generate", None)
        assert manager.get(job["id"])["status"] == "PASS_PENDING_USER_APPROVAL"
        assert {"requirement_lock", "spec_compile", "terminal"} <= {snapshot[2] for snapshot in store.snapshots}
        assert "analysis/spec_trace.json" in store.snapshots[-1][-1]
        original_commit = store.commit_stage
        failed = []
        def fail_approval_once(job, execution, stage, state, artifacts):
            if stage in {"state", "approve"} and state.get("status") == "FINALIZED" and not failed:
                failed.append(True)
                raise KnowledgeError("simulated storage outage")
            return original_commit(job, execution, stage, state, artifacts)
        store.commit_stage = fail_approval_once
        manager.action(job["id"], "approve", None)
        manager._run(job["id"], "approve", None)
        assert manager.get(job["id"])["status"] == "error"
        assert not (manager.root(job["id"]) / "final/FINAL_AGENT_SPEC.md").exists()
        # 승인 저장 실패는 대표 파일을 즉시 롤백한다.
        manager.action(job["id"], "approve", None)
        manager._run(job["id"], "approve", None)
        assert manager.get(job["id"])["status"] == "FINALIZED"
        nodes, _ = project(job["id"], store.snapshots[-1][3], store.snapshots[-1][4])
        assert next(node for node in nodes if node["logical_key"] == "decision:DEC-001")["attrs"]["status"] == "proposed"
    finally:
        manager.close()


class Tokenizer:
    def encode(self, text, add_special_tokens=False):
        return [ord(c) for c in text] + ([0, 0] if add_special_tokens else [])
    def decode(self, tokens, skip_special_tokens=True):
        return "".join(chr(c) for c in tokens if c)
    def num_special_tokens_to_add(self):
        return 2


class Model:
    prompts = {"query": "q:", "document": "d:"}
    default_prompt_name = "document"
    max_seq_length = 512
    tokenizer = Tokenizer()
    calls = []
    def get_sentence_embedding_dimension(self):
        return 3
    def encode_query(self, texts, **kwargs):
        self.calls.append(("query", texts))
        assert kwargs["batch_size"] == 1 and len(texts) == 1
        assert all(len(text) <= 508 for text in texts)
        return [[1, 0, 0] for _ in texts]
    def encode_document(self, texts, **kwargs):
        self.calls.append(("document", texts))
        assert kwargs["batch_size"] == 1 and len(texts) == 1
        assert all(len(text) <= 508 for text in texts)
        return [[0, 1, 0] for _ in texts]


def test_local_model_load_once_single_input_and_query_preprocessing(tmp_path):
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    calls = []
    def factory(path, **kwargs):
        calls.append(kwargs)
        return Model()
    model = LocalEmbedding(tmp_path, factory=factory)
    assert model.encode(["a" * 30, "한국어\n\nEnglish"]) == [[0, 1, 0], [0, 1, 0]]
    assert model.encode(["a" * 30], query=True) == [[1, 0, 0]]
    with pytest.raises(KnowledgeError, match="입력"):
        model.encode(["x" * 513])
    assert len(calls) == 1
    assert calls[0]["local_files_only"] is True and calls[0]["trust_remote_code"] is False
    original = model.info()
    (tmp_path / "config.json").write_text('{"changed":true}', encoding="utf-8")
    changed = LocalEmbedding(tmp_path, factory=factory).info()
    assert original["id"] != changed["id"]


def test_local_model_rejects_custom_code_and_redacts_failure(tmp_path):
    (tmp_path / "modules.json").write_text('[{"type":"untrusted.Custom"}]', encoding="utf-8")
    called = []
    model = LocalEmbedding(tmp_path, factory=lambda *a, **kw: called.append(True))
    with pytest.raises(KnowledgeError) as failure:
        model.info()
    assert not called and str(tmp_path) not in str(failure.value)


def test_cached_model_links_participate_in_fingerprint_and_external_links_are_rejected(tmp_path):
    root = tmp_path / "repo/snapshots/revision"
    blobs = tmp_path / "repo/blobs"
    root.mkdir(parents=True); blobs.mkdir()
    target = blobs / ("a" * 64)
    target.write_bytes(b"original weights")
    link = root / "model.safetensors"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("이 환경에서는 파일 심볼릭 링크를 만들 수 없습니다.")
    first = LocalEmbedding(root, factory=lambda *a, **kw: Model()).info()
    target.write_bytes(b"changed weights")
    second = LocalEmbedding(root, factory=lambda *a, **kw: Model()).info()
    assert first["id"] != second["id"]
    external = tmp_path / "external.json"
    external.write_text("{}", encoding="utf-8")
    (root / "config.json").symlink_to(external)
    with pytest.raises(KnowledgeError): LocalEmbedding(root, factory=lambda *a, **kw: Model()).info()


def test_model_does_not_open_unrelated_credentials_and_rejects_wrong_vector_width(tmp_path, monkeypatch):
    original_open = Path.open
    def guard(path, *args, **kwargs):
        assert path.name != "service-account.json"
        return original_open(path, *args, **kwargs)
    # 보호 파일 내용을 만들거나 읽지 않고, 해당 이름이 존재하는 상황만 모사한다.
    (tmp_path / "service-account.json").touch()
    monkeypatch.setattr(Path, "open", guard)
    class WrongWidth(Model):
        def encode_document(self, texts, **kwargs): return [[0, 1, 0, 0] for _ in texts]
    with pytest.raises(KnowledgeError, match="차원"):
        LocalEmbedding(tmp_path, factory=lambda *a, **kw: WrongWidth()).encode(["notes"])


def test_retry_requested_during_failed_indexing_is_not_lost():
    service = KnowledgeService(MemoryStore(), LocalEmbedding(None))
    entered, release = threading.Event(), threading.Event()
    calls = []
    def index():
        calls.append(True)
        if len(calls) == 1:
            entered.set(); assert release.wait(3); return False
        return True
    service.reindex = index
    service.schedule(); assert entered.wait(3)
    service.schedule(); release.set()
    service.future.result(timeout=3)
    assert len(calls) == 2 and service.running is False
    service.close()


def test_historical_provenance_is_bound_to_immutable_input_and_inactive_reuse_is_blocked(tmp_path):
    from backend.knowledge.trace import source_version
    root = tmp_path
    (root / "state").mkdir()
    old = decision(actor="user", text="SQLite", sources=["user_feedback"], requirement_ids=[])
    (root / "state/magi_state.json").write_text(json.dumps({"revision_feedback": "Use SQLite"}), encoding="utf-8")
    history = {"nodes": [{"action": "revise", "result": {"feedback": "Use SQLite"}}]}
    (root / "state/execution_history.json").write_text(json.dumps(history), encoding="utf-8")
    store = MemoryStore()
    store.actions["current"] = {"job_id": "job", "action": "revise", "input": "Add CSV"}
    service = KnowledgeService(store, LocalEmbedding(None))
    try:
        runtime = RunKnowledge(service, {"id": "job"}, root)
        bound = runtime.bind_decisions([old], [old])
        assert bound[0]["sources"] == [source_version("user_feedback", "Use SQLite")]
        validate_decisions(bound, {}, confirmed=runtime.confirmed_sources({}), previous=bound)
        runtime.retrieved["nodes"] = [{"id": "retired", "active": False, "kind": "decision"}]
        with pytest.raises(ValueError):
            validate_decisions([decision(reused_node_ids=["retired"])], sheet(), runtime.reusable_ids())
        retained = decision(reused_node_ids=["old-source"])
        validate_decisions([retained], sheet(), previous=[retained])
        with pytest.raises(ValueError):
            validate_decisions([{**retained, "text": "New choice"}], sheet(), previous=[retained])
    finally:
        service.close()


def test_trace_must_exist_in_assembled_section_and_fenced_examples_are_not_graph_sections():
    from backend.models import SpecResponse, RequirementLockSheet, RequirementItem
    from backend.services.spec_compiler import _assemble_locked_sections, _rendered_sections
    response = SpecResponse(**{key: "Implementation prose." for key in SpecResponse.model_fields if key not in {"decisions", "spec_links"}})
    response.out_of_scope = "Model-invented exclusion."
    locked = RequirementLockSheet(workflow_constraints=[], lock_id="lock", request_type="feature", request_summary="Notes",
                                  non_scope=[RequirementItem("NS-001", "No networking.", "user_request")])
    rendered = _assemble_locked_sections(response.markdown(), locked)
    link = {"item_id": "S1", "section": "out_of_scope", "quote": "Model-invented exclusion.", "requirement_ids": [], "decision_ids": []}
    with pytest.raises(ValueError): validate_links([link], [], locked.to_dict(), _rendered_sections(rendered))
    nodes, edges = project("job", {"requirement_lock_sheet": sheet()}, {
        "draft/approval_candidate_spec.en.md": "## 13. Architecture\nUse files.\n```md\n## Example heading\nREQ-001\n```\n"})
    assert len([node for node in nodes if node["kind"] == "spec"]) == 1
    assert not any(edge["kind"] == "implemented" for edge in edges)


def test_local_inference_is_serialized(tmp_path):
    entered, release = threading.Event(), threading.Event()
    class BlockingModel(Model):
        def encode_document(self, texts, **kwargs):
            entered.set()
            assert release.wait(3)
            return super().encode_document(texts, **kwargs)
    model = LocalEmbedding(tmp_path, factory=lambda *a, **kw: BlockingModel())
    threads = [threading.Thread(target=lambda: model.encode(["notes"])) for _ in range(2)]
    threads[0].start(); assert entered.wait(3)
    assert not model.lock.acquire(blocking=False)
    release.set(); threads[0].join(); threads[1].start(); threads[1].join()


class MemoryStore:
    """서비스와 작업 관리자 통합 테스트용 저장소. SQL 동작 검증과 구분한다."""
    config = SimpleNamespace(model_path=None, device="cpu")
    def __init__(self):
        self.saved_jobs, self.saved_projects, self.snapshots, self.vectors = {}, {}, [], {}
        self.active = None
        self.rows = [{"id": "node", "body": "Store notes offline."}]
        self.actions = {}
    def accept_job(self, job, payload):
        self.create_project(job["request"][:80], job["id"])
        self.record_action(job, payload)
    def projects(self): return list(self.saved_projects.values())
    def create_project(self, name, ident="c" * 32):
        self.saved_projects[ident] = {"id": ident, "name": name}
        return self.saved_projects[ident]
    def save_job(self, job):
        if job["project_id"] not in self.saved_projects: raise ValueError("Unknown project")
        self.saved_jobs[job["id"]] = deepcopy(job)
    def jobs(self): return list(deepcopy(self.saved_jobs).values())
    def record_action(self, job, payload):
        self.save_job(job)
        self.actions[job["execution_id"]] = {"id": job["execution_id"], "job_id": job["id"], "action": job["action"], "input": deepcopy(payload)}
    def action_records(self, job_id):
        return [item for item in self.actions.values() if item["job_id"] == job_id]
    def save_prompt_references(self, job_id, content):
        prior = next(item for item in reversed(self.snapshots) if item[0]['id'] == job_id)
        artifacts = {**prior[-1], 'state/prompt_references.json': content}
        self.commit_stage(prior[0], prior[1], 'prompt_references', prior[3], artifacts)
    def restore(self, job_id):
        matches = [s for s in self.snapshots if s[0]["id"] == job_id]
        return deepcopy(matches[-1][-1]) if matches else {}
    def commit_stage(self, job, execution, stage, state, artifacts):
        self.save_job(job)
        self.snapshots.append(deepcopy((job, execution, stage, state, artifacts)))
    def register_model(self, info): self.info = info
    def pending_embeddings(self, model_id):
        return [{"kind": "decision", "attrs": {}, **row} for row in self.rows if (row["id"], model_id) not in self.vectors][:1]
    def chunk_vector(self, chunk, model_id): return None
    def save_chunk(self, info, chunk, vector): pass
    def complete_chunks(self, node_id, model_id, expected): self.vectors[node_id, model_id] = True
    def activate_model(self, ident):
        if self.pending_embeddings(ident): return False
        self.active = {"id": ident}; return True
    def active_model(self): return self.active
    def embedding_failure(self): pass
    def search(self, query, **kwargs):
        self.search_kwargs = kwargs
        return {"nodes": [], "mode": "hybrid" if kwargs["vector"] is not None else "text"}


def test_embedding_failure_fallback_and_model_switch_is_complete(tmp_path):
    store = MemoryStore()
    missing = KnowledgeService(store, LocalEmbedding(None))
    assert not missing.reindex()
    assert missing.search("오프라인 메모")["mode"] == "text"
    assert missing.last_error
    missing.close()
    model = LocalEmbedding(tmp_path, factory=lambda *a, **kw: Model())
    service = KnowledgeService(store, model)
    store.active = {"id": "old"}
    assert service.search("오프라인 메모")["mode"] == "text"
    assert service.reindex()
    assert store.active["id"] == model.info()["id"]
    assert service.search("오프라인 메모")["mode"] == "hybrid"
    assert store.search_kwargs["vector"] == [1, 0, 0]
    service.close()


def test_run_commit_happens_before_completed_event_and_db_error_propagates(tmp_path):
    from backend.pipeline.builder import _stage
    events = []
    store = MemoryStore()
    service = KnowledgeService(store, LocalEmbedding(None))
    service.schedule = lambda: None
    runtime = RunKnowledge(service, {"id": "a" * 32, "project_id": "p", "execution_id": "e"}, tmp_path)
    store.saved_projects["p"] = {"id": "p"}
    token = CURRENT.set(runtime)
    try:
        def callback(event):
            if event["state"] == "completed": assert store.snapshots
            events.append(event)
        _stage("spec_compile", lambda state: {"status": "COMPILING"}, callback)({})
        store.commit_stage = lambda *args: (_ for _ in ()).throw(KnowledgeError("DB failed"))
        with pytest.raises(KnowledgeError):
            _stage("spec_compile", lambda state: {}, events.append)({})
    finally:
        CURRENT.reset(token); service.close()
    assert len([event for event in events if event["state"] == "completed"]) == 1


def test_each_committed_step_restores_its_own_document_without_terminal_snapshot(tmp_path):
    from backend.server.execution_history import ExecutionHistory
    root = tmp_path / "working"
    (root / "draft").mkdir(parents=True)
    history = ExecutionHistory(root)
    execution = history.start_execution("generate", input_data="Notes")
    store = MemoryStore()
    store.saved_projects["p"] = {"id": "p"}
    service = KnowledgeService(store, LocalEmbedding(None))
    service.schedule = lambda: None
    runtime = RunKnowledge(service, {"id": "job", "project_id": "p", "execution_id": execution}, root)
    try:
        history.stage(execution, "spec_compile", "started")
        (root / "draft/approval_candidate_spec.en.md").write_text("First draft", encoding="utf-8")
        original_commit = store.commit_stage
        store.commit_stage = lambda *args: (_ for _ in ()).throw(KnowledgeError("DB failed"))
        with pytest.raises(KnowledgeError): runtime.commit("spec_compile", {})
        assert history.graph()["nodes"][-1]["status"] == "running"
        assert not (root / "history").exists()
        store.commit_stage = original_commit
        runtime.commit("spec_compile", {})
        first_id = history.graph()["nodes"][-1]["id"]
        history.stage(execution, "spec_compile", "started")
        (root / "draft/approval_candidate_spec.en.md").write_text("Second draft", encoding="utf-8")
        runtime.commit("spec_compile", {})
        second_id = history.graph()["nodes"][-1]["id"]
        restored_root = tmp_path / "restored"
        restore_artifacts(restored_root, store.restore("job"))
        restored = ExecutionHistory(restored_root)
        assert restored.detail(first_id)["document"]["content"] == "First draft"
        assert restored.detail(second_id)["document"]["content"] == "Second draft"
    finally:
        service.close()


def test_restore_rebases_internal_paths_and_rejects_unmanaged_history_reference(tmp_path, monkeypatch):
    from backend.server.execution_history import ExecutionHistory
    state = {"run_id": "run", "output_dir": "old/root", "approval_candidate_spec": "old/root/draft.md",
             "project_dir": "actual/source/project"}
    restore_artifacts(tmp_path, {"state/magi_state.json": json.dumps(state), "draft/approval_candidate_spec.en.md": "Draft"})
    restored = json.loads((tmp_path / "state/magi_state.json").read_text(encoding="utf-8"))
    assert restored["output_dir"] == str(tmp_path.resolve())
    assert restored["approval_candidate_spec"] == str(tmp_path / "draft/approval_candidate_spec.en.md")
    assert restored["project_dir"] == "actual/source/project"
    original_read = Path.read_text
    def guard(path, *a, **kw):
        assert path.name != ".env"
        return original_read(path, *a, **kw)
    monkeypatch.setattr(Path, "read_text", guard)
    assert ExecutionHistory(tmp_path)._read_document({"ref": "history/.env"}) is None


def test_import_preview_apply_repeat_and_protected_paths(tmp_path):
    root = tmp_path / ("a" * 32)
    (root / "raw").mkdir(parents=True)
    (root / "raw/user_request.md").write_text("메모 앱", encoding="utf-8")
    (root / "job.json").write_text(json.dumps({"id": root.name, "request": "메모 앱", "demo": True, "provider": "mock"}), encoding="utf-8")
    assert import_legacy(tmp_path)[0]["status"] == "preview"
    store = MemoryStore()
    assert import_legacy(tmp_path, store)[0]["status"] == "imported"
    assert import_legacy(tmp_path, store)[0]["status"] == "already_imported"
    assert len(store.snapshots) == 1
    assert store.jobs()[0]["demo"] is True and store.jobs()[0]["provider"] == "mock"
    assert set(read_artifacts(root)) == {"raw/user_request.md"}
    restore_artifacts(tmp_path / "restore", {"../escape": "ignored", "raw/user_request.md": "restored"})
    assert not (tmp_path / "escape").exists()


def test_job_database_restore_project_assignment_and_gateway(tmp_path, monkeypatch):
    from backend.server.job_manager import JobManager
    from gateway.app import create_app
    store = MemoryStore()
    service = KnowledgeService(store, LocalEmbedding(None))
    manager = JobManager(tmp_path, knowledge=service)
    monkeypatch.setattr(manager, "_submit_locked", lambda *a: None)
    created = manager.create("메모 앱")
    assert created["project_id"] in store.saved_projects
    manager.jobs[created["id"]]["status"] = "error"
    manager._save_locked(manager.jobs[created["id"]])
    store.create_project("다른 프로젝트", "d" * 32)
    with pytest.raises(ValueError, match="지원이 종료"):
        manager.knowledge_call("projects.assign", {"id": created["id"], "project_id": "d" * 32})
    manager.close()
    restored = JobManager(tmp_path / "new", knowledge=KnowledgeService(store, LocalEmbedding(None)))
    assert restored.get(created["id"])["project_id"] == created["id"]
    from backend.server.execution_history import ExecutionHistory
    history = ExecutionHistory(restored.root(created["id"]))
    assert history.detail(history.graph()["nodes"][0]["id"])["result"]["request"] == "메모 앱"
    class Client:
        def __init__(self, url): pass
        def call(self, method, params=None): return restored.knowledge_call(method, params or {})
    app = create_app({"MAGI_PUBLIC_MODE": False, "TESTING": True, "MAGI_CLIENT_FACTORY": Client})
    with app.test_client() as client:
        assert len(client.get("/api/projects").json) == 2
        assert client.post("/api/projects", json={"name": "새 프로젝트"}).status_code == 410
        assert client.get("/api/knowledge/search?query=메모").json["mode"] == "text"
        assert client.get("/api/knowledge/graph?depth=oops").status_code == 400
    restored.close()


def test_database_action_receipt_is_independent_of_job_cache_writes(tmp_path, monkeypatch):
    from backend.server.job_manager import JobManager
    store = MemoryStore()
    manager = JobManager(tmp_path, knowledge=KnowledgeService(store, LocalEmbedding(None)))
    monkeypatch.setattr(manager, "_submit_locked", lambda *a: None)
    original_write = Path.write_text
    def fail_cache(path, *args, **kwargs):
        if ".job.json." in path.name:
            raise OSError("cache is unavailable")
        return original_write(path, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", fail_cache)
    try:
        job = manager.create("사용자 원문")
        assert store.saved_jobs[job["id"]]["status"] == "queued"
        assert store.action_records(job["id"])[0]["input"] == "사용자 원문"
    finally:
        manager.close()


def test_retrieved_context_is_bounded_and_has_no_dangling_edges():
    class GraphStore(MemoryStore):
        def __init__(self):
            super().__init__()
            self.records = {str(i): {"id": str(i), "project_id": "p", "job_id": "j", "active": True,
                "kind": "decision", "body": "body" * 10000,
                "attrs": {"scope": "product", "rationale": "reason" * 10000, "conditions": "condition" * 10000,
                          "unused": "unrelated" * 10000}} for i in range(70)}
        def graph(self, **kwargs):
            return {"nodes": list(self.records.values()), "edges": [
                {"id": f"{i}-{j}", "source": str(i), "target": str(j), "kind": "derived"}
                for i in range(70) for j in range(70) if i != j]}
        def node_records(self, identities):
            return {key: self.records[key] for key in identities}
    store = GraphStore()
    service = KnowledgeService(store, LocalEmbedding(None))
    service.search = lambda query, **kwargs: {"nodes": list(store.records.values())[:20], "mode": "text"}
    try:
        context = service.context("query")
        assert len(json.dumps(context, ensure_ascii=False)) <= 40000
        assert len(context["nodes"]) <= 60 and len(context["edges"]) <= 200
        identities = {node["id"] for node in context["nodes"]}
        assert all(edge["source"] in identities and edge["target"] in identities for edge in context["edges"])
        assert all("unused" not in node["attrs"] for node in context["nodes"])
    finally:
        service.close()


def test_knowledge_routes_through_real_websocket_transport(tmp_path):
    import asyncio
    from websockets.asyncio.server import serve
    from backend.server.app import MagiServer
    from gateway.app import create_app
    async def scenario():
        service = KnowledgeService(MemoryStore(), LocalEmbedding(None))
        server = MagiServer(tmp_path, knowledge=service)
        try:
            async with serve(server.handler, "127.0.0.1", 0) as socket_server:
                port = socket_server.sockets[0].getsockname()[1]
                def requests():
                    app = create_app({"MAGI_PUBLIC_MODE": False, "TESTING": True, "MAGI_SERVER_URL": f"ws://127.0.0.1:{port}"})
                    with app.test_client() as client:
                        created = client.post("/api/projects", json={"name": "통신 검증"})
                        assert created.status_code == 410
                        assert client.get("/api/projects").json == []
                        search = client.get("/api/knowledge/search?query=offline")
                        assert search.status_code == 200 and search.json["mode"] == "text"
                await asyncio.to_thread(requests)
        finally:
            server.manager.close()
    asyncio.run(scenario())


class Cursor:
    def __init__(self, rows=()): self.rows = list(rows)
    def fetchone(self): return self.rows[0] if self.rows else None
    def fetchall(self): return self.rows


class Connection:
    def __init__(self, handler): self.handler, self.queries, self.committed, self.rolled_back = handler, [], False, False
    def __enter__(self): return self
    def __exit__(self, typ, value, tb): self.committed, self.rolled_back = typ is None, typ is not None
    def execute(self, query, params=()):
        self.queries.append((query, params))
        return Cursor(self.handler(query, params))


def test_postgres_failure_rolls_back_and_never_exposes_driver_message():
    conn = Connection(lambda q, p: (_ for _ in ()).throw(OSError("fake connection detail")))
    store = KnowledgeStore(KnowledgeConfig({}), connect=lambda **kw: conn)
    with pytest.raises(KnowledgeError) as exc:
        store.projects()
    assert conn.rolled_back and "fake connection detail" not in str(exc.value)


def test_hybrid_rank_fusion_and_parameter_binding():
    def row(ident):
        return {"id": ident, "kind": "decision", "body": "notes", "attrs": {}, "active": True, "logical_key": ident}
    def handler(query, params):
        if "NOT EXISTS" in query: return []
        if "ts_rank" in query: return [row("a"), row("b")]
        if "embedding <=>" in query: return [row("b"), row("c")]
        return []
    conn = Connection(handler)
    store = KnowledgeStore(KnowledgeConfig({}), connect=lambda **kw: conn)
    result = store.search("메모 ' ; DROP TABLE x; --", vector=[1, 0], model_id="model")
    assert [node["id"] for node in result["nodes"]] == ["b", "a", "c"]
    assert result["mode"] == "hybrid" and conn.committed
    assert all("DROP TABLE" not in query for query, _ in conn.queries)


def test_schema_migration_requires_extension_and_is_versioned(caplog):
    caplog.set_level("INFO", logger="backend.knowledge.store")
    conn = Connection(lambda q, p: [])
    store = KnowledgeStore(KnowledgeConfig({}), connect=lambda **kw: conn)
    with pytest.raises(KnowledgeError, match="vector"):
        store.migrate()
    assert conn.rolled_back
    assert "failed stage=vector_check" in caplog.text
    assert "DB migration completed" not in caplog.text
    caplog.clear()
    conn = Connection(lambda q, p: [{"ok": 1}] if "pg_extension" in q else [])
    store = KnowledgeStore(KnowledgeConfig({}), connect=lambda **kw: conn)
    store.migrate()
    assert conn.committed and any("CREATE TABLE IF NOT EXISTS magi_nodes" in q for q, _ in conn.queries)
    assert any("INSERT INTO magi_schema_versions" in q for q, _ in conn.queries)
    assert "stage=execute migration=" in caplog.text
    assert "DB migration completed applied=" in caplog.text


def test_schema_migration_logs_setup_failure_without_driver_details(caplog):
    def fail(**kwargs):
        raise OSError("fake-sensitive-connection-detail")

    store = KnowledgeStore(KnowledgeConfig({}), connect=fail)
    with pytest.raises(KnowledgeError):
        store.migrate()
    assert "failed stage=transaction_setup" in caplog.text
    assert "DB transaction failed stage=connect exception_type=OSError sqlstate=None" in caplog.text
    assert "cause_type=OSError" in caplog.text
    assert "fake-sensitive-connection-detail" not in caplog.text
    assert "DB migration completed" not in caplog.text


@pytest.mark.parametrize("sqlstate,expected", [("57014", "57014"), ("fake-sensitive-detail", "None")])
def test_transaction_logs_setup_stage_and_only_valid_sqlstate(caplog, sqlstate, expected):
    class DriverError(Exception):
        pass

    error = DriverError("fake-sensitive-connection-detail")
    error.sqlstate = sqlstate

    def handler(query, params):
        if "pg_advisory_xact_lock" in query:
            raise error
        return []

    conn = Connection(handler)
    store = KnowledgeStore(KnowledgeConfig({}), connect=lambda **kw: conn)
    with pytest.raises(KnowledgeError):
        store.migrate()
    assert "DB transaction failed stage=maintenance_lock" in caplog.text
    assert f"sqlstate={expected}" in caplog.text
    assert "fake-sensitive" not in caplog.text
    assert conn.rolled_back


def test_invalid_config_is_redacted_and_environment_has_precedence(monkeypatch):
    for key in ("HOST", "PORT", "NAME", "USER", "PASSWORD", "SSLMODE"):
        monkeypatch.delenv("MAGI_DB_" + key, raising=False)
    assert KnowledgeConfig.from_env() is None
    monkeypatch.setenv("MAGI_DB_PORT", "5432")
    with pytest.raises(KnowledgeError): KnowledgeConfig.from_env()
    monkeypatch.delenv("MAGI_DB_PORT")
    monkeypatch.setenv("MAGI_DB_HOST", "test-host")
    with pytest.raises(KnowledgeError): KnowledgeConfig.from_env()
    for key in ("NAME", "USER", "PASSWORD"):
        monkeypatch.setenv("MAGI_DB_" + key, "fake-test-value")
    assert "fake-test-value" not in repr(KnowledgeConfig.from_env())


def test_graph_public_metadata_preserves_document_version_without_detail_body():
    row = {"id": "n", "body": "a" * 300, "attrs": {"artifact_hash": "version", "artifact_path": "spec.md", "title_path": ["Architecture"], "section": "architecture", "rationale": "detail only"}}
    result = KnowledgeStore._public(row)
    assert result["attrs"] == {"artifact_hash": "version", "artifact_path": "spec.md", "title_path": ["Architecture"], "section": "architecture"}
    assert len(result["body"]) == 240
    assert len(row["body"]) == 300 and "rationale" in row["attrs"]


def test_session_queue_failure_preserves_receipt_and_rejects_project(tmp_path, monkeypatch):
    from backend.server.job_manager import JobManager
    store = MemoryStore()
    service = KnowledgeService(store, LocalEmbedding(None))
    manager = JobManager(tmp_path, knowledge=service)
    monkeypatch.setattr(manager, "_submit_locked", lambda *a: (_ for _ in ()).throw(RuntimeError("queue unavailable")))
    try:
        with pytest.raises(ValueError):
            manager.create("메모", project_id="legacy")
        assert not store.projects()
        job = manager.create("메모")
        assert job["status"] == "error"
        assert job["project_id"] == job["id"]
        assert store.jobs()[0]["status"] == "error"
        assert store.action_records(job["id"])
    finally:
        manager.close()
