"""선택적 WASM PostgreSQL+pgvector SQL 통합 검증. 사용자 서버에는 연결하지 않는다."""

import json
from decimal import Decimal
from pathlib import Path
import shutil
import subprocess
import tempfile

import pytest

from backend.knowledge.config import KnowledgeConfig, KnowledgeError
from backend.knowledge.projection import digest
from backend.knowledge.store import KnowledgeStore


@pytest.fixture
def store():
    runtime = Path(tempfile.gettempdir()) / "magi-knowledge-validation"
    if not shutil.which("node") or not (runtime / "node_modules/@electric-sql/pglite-pgvector").is_dir():
        pytest.skip("별도 테스트용 PGlite+pgvector 런타임이 설치되지 않았습니다.")
    process = subprocess.Popen(["node", str(Path(__file__).with_name("pglite_bridge.mjs")), str(runtime)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert json.loads(process.stdout.readline())["ready"]
    class Result:
        def __init__(self, rows): self.rows = rows
        def fetchone(self): return self.rows[0] if self.rows else None
        def fetchall(self): return self.rows
    class Connection:
        def execute(self, sql, params=()):
            count = iter(range(1, 1000))
            while "%s" in sql:
                sql = sql.replace("%s", "$" + str(next(count)), 1)
            params = [value.obj if hasattr(value, "obj") else value for value in params]
            params = [str(value) if isinstance(value, Decimal) else value for value in params]
            process.stdin.write(json.dumps({"sql": sql, "params": params}, ensure_ascii=False) + "\n")
            process.stdin.flush()
            response = json.loads(process.stdout.readline())
            if "error" in response: raise RuntimeError(response["error"])
            for row in response["rows"]:
                if "total" in row: row["total"] = int(row["total"])
            return Result(response["rows"])
        def __enter__(self): self.execute("BEGIN"); return self
        def __exit__(self, typ, value, tb): self.execute("ROLLBACK" if typ else "COMMIT")
    instance = KnowledgeStore(KnowledgeConfig({}), connect=lambda **kw: Connection())
    try:
        instance.migrate()
        yield instance
    finally:
        process.stdin.close()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired: process.terminate(); process.wait(timeout=5)


def test_real_sql_versions_search_graph_embedding_switch_and_restore(store):
    store.migrate()  # 재실행해도 스키마를 중복 생성하지 않는다.
    project = store.create_project("메모")
    job = {"id": "a" * 32, "project_id": project["id"], "request": "메모 앱"}
    state = {"user_request": "메모 앱", "requirement_lock_sheet": {"workflow_constraints": [],
        "mandatory_requirements": [{"id": "REQ-001", "text": "Store notes offline.", "source": "user_request"}]}}
    doc = "## 13. Architecture\n\nStore notes offline. REQ-001"
    snapshot = store.commit_stage(job, "execution", "spec_compile", state, {"draft/approval_candidate_spec.en.md": doc})
    assert store.commit_stage(job, "execution", "spec_compile", state, {"draft/approval_candidate_spec.en.md": doc}) == snapshot
    graph = store.graph(project_id=project["id"])
    assert len(graph["nodes"]) == 3 and len(graph["edges"]) == 2
    assert store.search("offline")["nodes"]
    spec = next(node for node in graph["nodes"] if node["kind"] == "spec")
    assert store.node(spec["id"])["document"] == doc
    assert store.artifact_page(job["id"], "draft/approval_candidate_spec.en.md", digest(doc))["content"] == doc
    assert len(store.graph(node_id=spec["id"], depth=2)["nodes"]) == 3
    assert store.graph(limit=1)["has_more"]
    ids = {node["id"] for node in graph["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in graph["edges"])
    assert len(store.graph(node_id=spec["id"], depth=0)["nodes"]) == 1
    assert len(store.graph(node_id=spec["id"], depth=1)["nodes"]) == 2
    assert store.graph(project_id="missing")["nodes"] == []
    assert all(n["kind"] == "requirement" for n in store.graph(kind="requirement")["nodes"])
    assert all(n["active"] and n["attrs"]["status"] == "confirmed" for n in store.graph(status="confirmed")["nodes"])
    for invalid in ({"depth": 3}, {"limit": 101}):
        with pytest.raises(ValueError): store.graph(**invalid)

    for model in ({"id": "first", "dimensions": 3, "max_length": 20}, {"id": "next", "dimensions": 4, "max_length": 20}):
        store.register_model(model)
        assert not store.activate_model(model["id"])
        while rows := store.pending_embeddings(model["id"]):
            row = rows[0]
            chunk = {"id": digest([row["id"], model["id"]]), "node_id": row["id"], "ordinal": 0, "rule": "test",
                     "title_path": "", "body": row["body"], "input": row["body"], "input_hash": digest(row["body"]),
                     "source_ranges": [{"field": "body", "start": 0, "end": len(row["body"])}]}
            store.save_chunk(model, chunk, [1.0] + [0.0] * (model["dimensions"]-1))
            store.complete_chunks(row["id"], model["id"], 1)
        assert store.activate_model(model["id"])
        assert store.active_model()["id"] == model["id"]
        assert store.search("오프라인 메모", vector=[1.0] + [0.0] * (model["dimensions"]-1), model_id=model["id"])["nodes"]
    state["requirement_lock_sheet"]["mandatory_requirements"][0]["text"] = "Store notes online."
    store.commit_stage(job, "execution2", "requirement_lock", state, {})
    history = store.graph(status="superseded")
    assert any(node["kind"] == "requirement" for node in history["nodes"])
    old_requirement = next(node for node in history["nodes"] if node["kind"] == "requirement")
    assert any(edge["kind"] == "superseded" for edge in store.node(old_requirement["id"])["edges"])
    assert json.loads(store.restore(job["id"])["state/magi_state.json"]) == state
    assert store.jobs()[0]["project_id"] == project["id"]


def test_chunk_resume_latest_version_filters_and_tail_context(store, tmp_path):
    from backend.knowledge.embedding import LocalEmbedding
    from backend.knowledge.runtime import KnowledgeService
    from test_knowledge import Model
    class InterruptModel(Model):
        def encode_document(self, texts, **kwargs):
            if self.fail and self.count == 1:
                raise RuntimeError("일시 중단")
            self.count += 1
            return super().encode_document(texts, **kwargs)
        fail, count = True, 0
    fake = InterruptModel()
    embedder = LocalEmbedding(tmp_path, factory=lambda *a, **kw: fake)
    service = KnowledgeService(store, embedder)
    project = store.create_project("청크")
    job = {"id": "f" * 32, "project_id": project["id"]}
    state = {"user_request": "테스트", "requirement_lock_sheet": {"workflow_constraints": [], "mandatory_requirements": [
        {"id": "REQ-900", "text": "일반 문맥. " * 180 + "후반특수조건을 보존한다.", "source": "user_request"}]}}
    try:
        store.commit_stage(job, "v1", "requirement_lock", state, {})
        assert not service.reindex()
        with store.transaction() as conn:
            completed_count = conn.execute("SELECT count(*) AS total FROM magi_chunk_vectors").fetchone()["total"]
        assert completed_count >= 1 and fake.count == 1
        assert store.active_model() is None
        assert store.search("후반특수조건")["nodes"]
        fake.fail = False
        assert service.reindex()
        calls = fake.count
        assert service.reindex() and fake.count == calls
        result = service.search("후반특수조건", project_id=project["id"], kind="requirement")
        assert len(result["nodes"]) == 1
        match = result["nodes"][0]["matches"][0]
        assert "후반특수조건" in match["quote"]
        assert match["source_ranges"][0]["start"] > 0
        assert "후반특수조건" in service.context("후반특수조건")["nodes"][0]["body"]
        assert not service.search("후반특수조건", project_id="other")["nodes"]
        assert not service.search("후반특수조건", status="confirmed")["nodes"]
        state["requirement_lock_sheet"]["mandatory_requirements"][0]["text"] = "최신버전조건"
        store.commit_stage(job, "v2", "requirement_lock", state, {})
        assert service.search("최신버전조건")["nodes"][0]["body"] == "최신버전조건"
        assert not store.search("후반특수조건")["nodes"]
        assert store.search("후반특수조건", status="superseded")["nodes"]
        assert service.reindex()
        assert service.search("최신버전조건")["nodes"][0]["matches"]
    finally:
        service.close()


def test_relock_does_not_attach_new_requirement_to_old_draft(store):
    from copy import deepcopy
    project = store.create_project("재확정")
    job = {"id": "c" * 32, "project_id": project["id"]}
    state = {"user_request": "Notes", "requirement_lock_sheet": {"workflow_constraints": [],
        "mandatory_requirements": [{"id": "REQ-001", "text": "Use files.", "source": "user_request"}]}}
    artifacts = {"draft/approval_candidate_spec.en.md": "## 13. Architecture\nUse files. REQ-001"}
    store.commit_stage(job, "first", "spec_compile", state, artifacts)
    old_spec = next(n for n in store.graph()["nodes"] if n["kind"] == "spec")
    revised = deepcopy(state)
    revised["requirement_lock_sheet"]["mandatory_requirements"][0]["text"] = "Use Postgres."
    store.commit_stage(job, "next", "requirement_lock", revised, artifacts)
    assert not any(n["kind"] == "spec" for n in store.graph()["nodes"])
    current = next(n for n in store.graph()["nodes"] if n["kind"] == "requirement")
    assert not any(e["target"] == old_spec["id"] for e in store.node(current["id"])["edges"])
    store.commit_stage(job, "next", "terminal", revised, artifacts)
    assert not any(n["kind"] == "spec" for n in store.graph()["nodes"])


def test_reverted_content_has_new_version_and_old_replay_does_not_rewind_job(store):
    from copy import deepcopy
    project = store.create_project("버전")
    old_job = {"id": "d" * 32, "project_id": project["id"], "status": "running"}
    state = {"user_request": "Notes", "requirement_lock_sheet": {"workflow_constraints": [],
        "mandatory_requirements": [{"id": "REQ-001", "text": "Use files.", "source": "user_request"}]}}
    versions = []
    for index, text in enumerate(("Use files.", "Use Postgres.", "Use files.")):
        data = deepcopy(state)
        data["requirement_lock_sheet"]["mandatory_requirements"][0]["text"] = text
        job = {**old_job, "status": "completed"} if index else old_job
        store.commit_stage(job, str(index), "requirement_lock", data, {})
        versions.append(next(n["id"] for n in store.graph()["nodes"] if n["kind"] == "requirement"))
    assert len(set(versions)) == 3
    assert any(e["source"] == versions[1] and e["target"] == versions[2] for e in store.node(versions[2])["edges"])
    store.commit_stage(old_job, "0", "requirement_lock", state, {})
    assert store.jobs()[0]["status"] == "completed"
    assert next(n["id"] for n in store.graph()["nodes"] if n["kind"] == "requirement") == versions[2]
    with store.transaction() as conn:
        conn.execute("UPDATE magi_snapshots SET created_at='2026-01-01'")
    assert json.loads(store.restore(old_job["id"])["state/magi_state.json"])["requirement_lock_sheet"]["mandatory_requirements"][0]["text"] == "Use files."


def test_search_filters_apply_before_top_k_and_ids_are_searchable(store):
    project = store.create_project("검색")
    job = {"id": "e" * 32, "project_id": project["id"]}
    state = {"user_request": "Notes", "requirement_lock_sheet": {"workflow_constraints": [], "mandatory_requirements": [
        {"id": "REQ-"+str(i), "text": "notes", "source": "user_request"} for i in range(30)]}}
    store.commit_stage(job, "first", "requirement_lock", state, {})
    assert store.search("REQ-29")["nodes"][0]["attrs"]["requirement_id"] == "REQ-29"
    assert store.search("Notes", kind="input")["nodes"][0]["kind"] == "input"
    assert store.search("notes", kind="decision")["nodes"] == []
    state["requirement_lock_sheet"]["mandatory_requirements"][0]["text"] = "new notes"
    store.commit_stage(job, "next", "requirement_lock", state, {})
    assert store.search("notes", status="superseded")["nodes"]
    assert all(not n["active"] for n in store.search("notes", status="superseded")["nodes"])


def test_accepted_user_input_survives_without_artifact_history_and_unknown_model_is_rejected(store):
    project = store.create_project("접수")
    job = {"id": "f" * 32, "project_id": project["id"], "execution_id": "accepted", "action": "answer"}
    payload = [{"question_id": "Q1", "answer": "오프라인 저장"}]
    store.record_action(job, payload)
    store.commit_stage(job, "accepted", "state", {"user_request": "Notes"}, {})
    assert store.action_records(job["id"])[0]["input"] == payload
    store.register_model({"id": "known", "dimensions": 3, "max_length": 20})
    store.activate_model("known")
    with pytest.raises(ValueError): store.activate_model("missing")
    assert store.active_model()["id"] == "known"


def test_document_offsets_are_unicode_codepoints(store):
    project = store.create_project("원문")
    job = {"id": "ab" * 16, "project_id": project["id"]}
    doc = "## 13. Architecture\n" + "😀" * 13000 + "END"
    store.commit_stage(job, "first", "spec_compile", {}, {"draft/approval_candidate_spec.en.md": doc})
    node = next(n for n in store.graph()["nodes"] if n["kind"] == "spec")
    detail = store.node(node["id"])
    page = store.artifact_page(job["id"], "draft/approval_candidate_spec.en.md", digest(doc), detail["document_next_offset"])
    assert detail["document"] + page["content"] == doc


def test_translation_commit_preserves_latest_state_and_survives_stale_cache_capture(store):
    project = store.create_project("번역 저장")
    job = {"id": "bc" * 16, "project_id": project["id"], "status": "running"}
    state = {"user_request": "Notes", "status": "COMPILING"}
    artifacts = {"draft/approval_candidate_spec.en.md": "## 1. Mission\nNotes"}
    store.commit_stage(job, "first", "spec_compile", state, artifacts)
    path = "translations/" + "a" * 64 + "/translation.ko.json"
    validation = "translations/" + "a" * 64 + "/validation.json"
    store.save_translation(job["id"], {path: '{"content":"번역본"}', validation: '{"status":"validated"}'})
    assert json.loads(store.restore(job["id"])["state/magi_state.json"])["status"] == "COMPILING"
    store.commit_stage({**job, "status": "completed"}, "second", "terminal", {**state, "status": "FINALIZED"},
                       {**artifacts, path: "partial cache"})
    assert store.restore(job["id"])[path] == '{"content":"번역본"}'
    assert store.restore(job["id"])[validation] == '{"status":"validated"}'
    store.commit_stage(job, "first", "spec_compile", state, {**artifacts, path: "another partial cache"})
    assert store.jobs()[0]["status"] == "completed"
    with pytest.raises(ValueError): store.save_translation(job["id"], {".env": "invalid path"})


def test_real_sql_transaction_rolls_back_invalid_relation(store):
    project = store.create_project("실패 테스트")
    job = {"id": "b" * 32, "project_id": project["id"]}
    state = {"user_request": "request", "requirement_lock_sheet": {"workflow_constraints": [], "decisions": [{
        "id": "DEC", "text": "Choice", "actor": "llm", "rationale": "Reason", "conditions": "", "sources": [],
        "requirement_ids": [], "reused_node_ids": ["missing-node"]}]}}
    with pytest.raises(KnowledgeError):
        store.commit_stage(job, "execution", "spec_compile", state, {})
    assert store.jobs() == [] and store.graph()["nodes"] == []


def test_product_scope_excludes_old_nodes_from_search_and_index_without_rewriting(store):
    project = store.create_project("분류 경계")
    job = {"id": "c" * 32, "project_id": project["id"]}
    state = {"user_request": "메모", "requirement_lock_sheet": {"workflow_constraints": [],
        "mandatory_requirements": [{"id": "REQ-001", "text": "Legacy searchable marker.", "source": "user_request"}]}}
    store.commit_stage(job, "first", "requirement_lock", state, {})
    with store.transaction() as conn:
        conn.execute("UPDATE magi_nodes SET attrs=attrs-'scope' WHERE kind='requirement'")
    before = store.graph()
    assert any(node["kind"] == "requirement" for node in before["nodes"])
    assert store.search("Legacy searchable")["nodes"] == []
    store.register_model({"id": "scoped", "dimensions": 3, "max_length": 512})
    assert store.pending_embeddings("scoped") == []
    assert store.activate_model("scoped")
    assert store.graph() == before
    state["requirement_lock_sheet"]["mandatory_requirements"][0].update(id="REQ-002", text="Current searchable marker.")
    store.commit_stage(job, "second", "requirement_lock", state, {})
    assert store.search("Current searchable")["nodes"]
    assert len(store.pending_embeddings("scoped")) == 1


def test_resolution_snapshot_restores_diagnostics_and_question_context(store, tmp_path):
    from test_review_resolution import ResolutionProvider, issue, stage_for, state_for
    from backend.knowledge.runtime import read_artifacts
    item = issue(resolution_kind="user_decision", decision_question="재사용을 허용하나요?")
    state = state_for(item)
    def ask(context):
        from test_review_decisions import resolution_value
        value = resolution_value([{**context['issues'][0], 'resolution_kind': 'user_decision', 'decision_question': item.decision_question}])
        return value
    state.update(stage_for(tmp_path, ResolutionProvider(ask))(state))
    project = store.create_project("해결 판단 저장")
    job = {"id": "d" * 32, "project_id": project["id"]}
    artifacts = read_artifacts(tmp_path)
    artifacts["state/magi_state.json"] = json.dumps(state, ensure_ascii=False)
    snapshot = store.commit_stage(job, "resolution-execution", "review_resolution", state, artifacts)
    assert store.commit_stage(job, "resolution-execution", "review_resolution", state, artifacts) == snapshot
    restored = store.restore(job["id"])
    saved = json.loads(restored["state/magi_state.json"])
    assert saved["resolution_history"] == state["resolution_history"]
    assert saved["review_questions"][0]["missing_information"]
    assert json.loads(restored["review/resolution.json"])["draft_hash"] == state["resolution_history"][-1]["draft_hash"]
    review = next(node for node in store.graph()["nodes"] if node["kind"] == "review")
    assert store.node(review["id"])["attrs"]["decision_key"] == item.decision_key


def test_session_acceptance_atomicity_and_graph_selection(store):
    job = {"id": "9" * 32, "project_id": "9" * 32, "request": "세션", "execution_id": "receipt", "action": "generate"}
    store.accept_job(job, job["request"])
    assert store.jobs() == [job]
    assert store.action_records(job["id"])[0]["input"] == "세션"
    failed = {**job, "id": "8" * 32, "project_id": "8" * 32}
    with pytest.raises(KnowledgeError):
        store.accept_job(failed, "duplicate receipt")
    assert [p["id"] for p in store.projects()] == [job["id"]]
    with store.transaction() as conn:
        for i in range(125):
            kind = "requirement" if i == 0 else "spec"
            conn.execute("INSERT INTO magi_nodes(id,content_id,job_id,logical_key,kind,body,attrs) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                         (str(i), str(i), job["id"], str(i), kind, "sessionneedle", store._json({"scope": "product"})))
            if i:
                conn.execute("INSERT INTO magi_edges(id,source,target,kind,attrs) VALUES (%s,%s,%s,%s,%s)",
                             ("e"+str(i), "0", str(i), "implemented", store._json({})))
    graph = store.graph(job_id=job["id"])
    assert len(graph["nodes"]) == 100 and graph["has_more"]
    assert graph["edges"] and any(n["kind"] == "requirement" for n in graph["nodes"])
    assert graph == store.graph(job_id=job["id"])
    assert not store.search("sessionneedle", job_id="missing")["nodes"]
    assert store.search("sessionneedle", job_id=job["id"])["nodes"]
    assert not store.graph(job_id="missing")["nodes"]
