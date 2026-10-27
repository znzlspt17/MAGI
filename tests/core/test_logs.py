"""로그 권한 경계·제한된 검색·실제 HTTP 응답 처리 검증."""

from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from urllib.parse import parse_qs

import pytest
from flask import Flask
from werkzeug.datastructures import MultiDict

from gateway.logs import LogError, LogStore, filters
from protocol.logging import TRACE_ID, configure_logging, get_logger, log_context
from protocol.messages import parse_request


@pytest.fixture
def store_server():
    requests = []
    state = {"status": 200, "body": b'{"_time":"2026-10-27T00:00:00Z","service":"backend","level":"info","_msg":"test"}\n'}
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()))
            self.send_response(state["status"]); self.end_headers(); self.wfile.write(state["body"])
        def do_GET(self):
            self.send_response(200); self.end_headers()
            self.wfile.write(b'vl_free_disk_space_bytes{path="/storage"} 10\nvl_total_disk_space_bytes{path="/storage"} 100\nvl_storage_is_read_only{path="/storage"} 0\n')
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    yield LogStore(f"http://127.0.0.1:{server.server_port}"), requests, state
    server.shutdown(); server.server_close(); thread.join()


@pytest.mark.parametrize("args", [
    {"query": "*"}, {"service": "portainer"}, {"level": "trace"}, {"limit": "501"},
    {"limit": "0"}, {"offset": "1"}, {"trace_id": 'a" OR *'}, {"q": "a\n"},
    {"start": "2020-01-01T00:00:00Z"}, {"end": "2026-10-27"},
    MultiDict([("service", "backend"), ("service", "gateway")]),
])
def test_invalid_search_never_reaches_storage(args, store_server):
    store, calls, _ = store_server
    with pytest.raises(LogError) as exc:
        store.search(args)
    assert exc.value.status == 400 and not calls


def test_search_encodes_literal_bounds_and_lookahead(store_server):
    store, calls, state = store_server
    state["body"] *= 3
    result = store.search({"q": '" OR * | delete', "limit": "2"})
    assert len(result["items"]) == 2 and result["next_offset"] == 2
    assert result["storage"]["state"] == "ready"
    assert calls[0]["limit"] == ["3"] and calls[0]["timeout"] == ["5s"]
    assert '_msg:*' + json.dumps('" OR * | delete') + '*' in calls[0]["query"][0]
    assert "start" in calls[0] and "end" in calls[0]
    next_result = store.search({"start": result["start"], "end": result["end"], "offset": "2"})
    assert next_result["end"] == result["end"]


def test_storage_errors_and_redaction(store_server):
    store, _, state = store_server
    for body in (b"not-json", b"[]\n", b"x" * (4 * 1024 * 1024 + 1)):
        state["body"] = body
        with pytest.raises(LogError): store.search({})
    state["status"] = 302
    with pytest.raises(LogError): store.search({})
    with pytest.raises(LogError) as exc: LogStore("").search({})
    assert exc.value.code == "not_configured"
    state.update(status=200, body=json.dumps({"_msg": "password=fake-only-value", "service": "gateway", "level": "bogus", "private": "must-not-return"}).encode())
    item = store.search({})["items"][0]
    assert "fake-only-value" not in json.dumps(item)
    assert "private" not in item["fields"] and item["level"] == "unknown"


def test_status_uses_actual_storage_metrics_and_heartbeat(store_server):
    store, _, state = store_server
    status = store.status()
    assert status["free_bytes"] == 10 and status["collector_seen"]
    assert any("여유" in value for value in status["warnings"])
    state["body"] = b""
    assert not store.status()["collector_seen"]


@pytest.mark.parametrize("role,public,status", [("admin", True, 200), ("user", True, 403), (None, True, 401), ("admin", False, 403)])
def test_admin_boundary(role, public, status, monkeypatch):
    from gateway.public import install
    from gateway.client import ClientError
    app = Flask(__name__)
    app.config.update(PUBLIC_MODE=public, PUBLIC_ORIGIN="https://magi.test", LOCAL_LOGIN=False, PROXY_HOPS=0, LOG_STORE_URL="http://unused:9428")
    class Client:
        def call(self, method):
            assert method == "auth.me"
            if role is None: raise ClientError("login required", status=401)
            return {"role": role}
    calls = []
    monkeypatch.setattr(LogStore, "search", lambda self, args: calls.append(True) or {"items": []})
    install(app, lambda: Client())
    response = app.test_client().get("/api/admin/logs", base_url="https://magi.test")
    assert response.status_code == status
    assert bool(calls) == (status == 200)
    if status == 200: assert response.headers["Cache-Control"] == "no-store"
    assert TRACE_ID.get() is None


def test_native_and_stdlib_json_context_and_no_exception_body():
    output = io.StringIO(); configure_logging("backend", stream=output)
    logger = get_logger("backend.test")
    with log_context(trace_id="a" * 24):
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(copy_context().run, logger.info, "작업 시작", job_id="job").result()
            pool.submit(logger.info, "next").result()
        try: raise ValueError("sensitive-error-body")
        except ValueError: logger.exception("failed", password="fake-password")
        logging.getLogger("gateway.app").warning("safe warning")
    logger.debug("invisible")
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(rows) == 4 and rows[0]["trace_id"] == "a" * 24
    assert "trace_id" not in rows[1] and rows[2]["exception_type"] == "ValueError"
    assert "sensitive-error-body" not in output.getvalue() and "fake-password" not in output.getvalue()
    assert all(row["service"] == "backend" and row["timestamp"] for row in rows)
    configure_logging("backend", stream=output); configure_logging("backend", stream=output)
    logging.getLogger("gateway.app").warning("once")
    assert sum(json.loads(line)["message"] == "once" for line in output.getvalue().splitlines()) == 1
    import sys
    configure_logging("backend")


def test_trace_protocol_is_optional_and_bounded():
    request = {"request_id": "rpc", "method": "list", "params": {}}
    assert parse_request(json.dumps(request)) == request
    assert parse_request(json.dumps({**request, "trace_id": "a" * 24}))["trace_id"] == "a" * 24
    for value in (None, {}, "private", "a" * 65):
        assert parse_request(json.dumps({**request, "trace_id": value})) is None
