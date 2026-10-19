"""선택적 Playwright 브라우저 검증. 가짜 API만 사용한다."""

from pathlib import Path
import shutil
import subprocess
import threading

import pytest
from werkzeug.serving import make_server
from gateway.app import create_app


def test_knowledge_browser_flow():
    node = shutil.which("node")
    packages = Path(node).parent.parent / "node_modules" if node else Path("/missing")
    if not (packages / "playwright").is_dir():
        pytest.skip("Playwright Node 런타임이 없습니다.")
    nodes = [{"id": "n" + str(i), "job_id": "a" * 32, "project_id": "p", "active": True,
              "kind": kind, "body": text, "attrs": {"status": "proposed"}}
             for i, (kind, text) in enumerate((("decision", "오프라인 메모 저장 선택"), ("requirement", "REQ-001: Store offline"), ("spec", "Use local storage.")))]
    edges = [{"id": "e1", "source": "n0", "target": "n1", "kind": "derived"},
             {"id": "e2", "source": "n1", "target": "n2", "kind": "implemented"}]
    projects = [{"id": "p", "name": "메모 프로젝트 · " + "아주 긴 한국어 프로젝트 제목 " * 10}]
    document = "# Final Agent Specification\n\n" + "😀" * 12010 + "END"
    class Client:
        def __init__(self, url): pass
        def events(self):
            yield {"event": "ready"}
        def call(self, method, params=None):
            if method == "list": return [{"id": ident * 32, "request": "메모 세션", "created_at": "2026-10-19T00:00:00Z", "status": "FINALIZED"} for ident in ("a", "b")]
            if method == "cleanup.catalog": return {"jobs": [], "projects": projects, "database": True, "pending": []}
            if method == "projects.list": return projects
            if method == "projects.create":
                result = {"id": "new", "name": params["name"]}; projects.append(result); return result
            if method == "projects.assign": return {"id": params["id"], "project_id": params["project_id"]}
            if method == "knowledge.graph": return {"nodes": nodes, "edges": edges, "has_more": False}
            if method == "knowledge.search":
                return {"nodes": [{**nodes[0], "matches": [{"chunk_id": "c1", "quote": "검색된 청크 인용문", "source_ranges": [{"field": "body", "start": 0, "end": 8}]}]}], "mode": "hybrid"}
            if method == "knowledge.node":
                result = next(node for node in nodes if node["id"] == params["node_id"])
                return {**result, "edges": edges, "document": document[:12000], "document_has_more": True, "document_next_offset": 12000}
            if method == "knowledge.document":
                offset = params["offset"]
                content = document[offset:offset+12000]
                return {"content": content, "next_offset": offset+len(content), "has_more": offset+len(content) < len(document)}
            if method == "knowledge.retry": return {"status": "queued"}
            raise AssertionError(method)
    app = create_app({"MAGI_PUBLIC_MODE": False, "TESTING": True, "MAGI_CLIENT_FACTORY": Client})
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run([node, str(Path(__file__).with_name("knowledge_ui.mjs")), str(packages),
             f"http://127.0.0.1:{server.server_port}", str(root / ".pytest_cache/knowledge-desktop.png"),
             str(root / ".pytest_cache/knowledge-mobile.png")], capture_output=True, text=True, encoding="utf-8", timeout=60,
             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if "Executable doesn't exist" in result.stderr:
            pytest.skip("Playwright Chromium이 설치되지 않았습니다.")
        assert result.returncode == 0, result.stderr
        print(result.stdout)
    finally:
        server.shutdown(); thread.join(timeout=5)


def test_graph_projection_boundaries():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node 런타임이 없습니다.")
    result = subprocess.run([node, str(Path(__file__).with_name("graph_projection.cjs"))], capture_output=True, text=True, timeout=10,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr
