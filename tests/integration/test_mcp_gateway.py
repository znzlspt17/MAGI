"""게이트웨이·RPC 파서·사용자 접근 서비스의 MCP 경계를 함께 검증한다."""

import json
from types import SimpleNamespace

from cryptography.fernet import Fernet
from flask import Flask, request

from backend.access.context import AccessError
from backend.access.service import PublicService
from backend.access.store import AccessStore
from gateway.client import ClientError
from gateway.public import install
from protocol.messages import parse_request


def test_mcp_gateway_auth_csrf_crud_and_oauth_callback_binding(store, monkeypatch):
    monkeypatch.setenv("MAGI_MCP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    access = AccessStore(store)
    sid = access.login("mcp-gateway-user", "fake-test-pepper")
    user = access.session(sid)
    service = PublicService(SimpleNamespace(knowledge=SimpleNamespace(store=store)))
    called = []
    monkeypatch.setattr("backend.mcp_client.oauth.callback", lambda *args: called.append(args))

    class RPC:
        def call(self, method, params=None):
            packet = {"request_id": "test", "method": method, "params": params or {}}
            for target, value in (("session", request.cookies.get("__Host-session")),
                                  ("csrf", request.headers.get("X-CSRF-Token")),
                                  ("idempotency_key", request.headers.get("Idempotency-Key"))):
                if value is not None:
                    packet[target] = value
            packet = parse_request(json.dumps(packet))
            assert packet is not None
            try:
                return service.invoke(packet, None)
            except AccessError as exc:
                raise ClientError(str(exc), status=401 if exc.code in {"unauthorized", "session"} else 403) from None

    app = Flask(__name__)
    app.config.update(TESTING=True, PUBLIC_MODE=True, PUBLIC_ORIGIN="https://magi.test", LOCAL_LOGIN=False,
                      PROXY_HOPS=0, LOG_STORE_URL="")
    install(app, lambda: RPC())
    browser = app.test_client()
    origin = "https://magi.test"

    assert browser.get("/api/mcp/connections", base_url=origin).status_code == 401
    browser.set_cookie("__Host-session", sid, domain="magi.test")
    body = {"name": "docs", "url": "https://example.com/mcp", "auth_type": "none"}
    assert browser.post("/api/mcp/connections", base_url=origin, json=body,
                        headers={"Origin": origin}).status_code == 403
    headers = {"Origin": origin, "X-CSRF-Token": user["csrf"], "Idempotency-Key": "operation-gateway-1"}
    created = browser.post("/api/mcp/connections", base_url=origin, json=body, headers=headers)
    assert created.status_code == 200
    ident = created.json["id"]
    assert browser.get("/api/mcp/connections", base_url=origin).json["connections"][0]["id"] == ident
    assert browser.get(f"/api/mcp/connections/{ident}", base_url=origin).json["id"] == ident
    headers["Idempotency-Key"] = "operation-gateway-2"
    assert browser.patch(f"/api/mcp/connections/{ident}", base_url=origin, json={"name": "renamed"}, headers=headers).json["name"] == "renamed"
    headers["Idempotency-Key"] = "operation-gateway-3"
    assert browser.delete(f"/api/mcp/connections/{ident}", base_url=origin, headers=headers).json["ok"] is True

    response = browser.get("/auth/mcp/callback?state=fake-state&code=fake-code", base_url=origin)
    assert response.status_code == 302 and response.headers["Location"] == "/settings/mcp"
    assert called[0][1:4] == (user["id"], sid, "fake-state")
    browser.delete_cookie("__Host-session", domain="magi.test")
    response = browser.get("/auth/mcp/callback?state=fake-state&code=fake-code", base_url=origin)
    assert response.headers["Location"] == "/settings/mcp?oauth=failed" and len(called) == 1
