"""사용자별 연결과 중복 방지 경계를 테스트 저장소에서 검증한다."""

import json
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from backend.access.context import ACTOR, AccessError
from backend.access.service import PublicService
from backend.access.store import AccessStore
from backend.mcp_client.service import MCPService


def actor(store, name):
    access = AccessStore(store)
    sid = access.login(name, "fake-test-pepper")
    return sid, access.session(sid)


def tool(schema_hash="v1"):
    return {"name": "find", "description": "문서 검색", "read_only_hint": True,
            "destructive_hint": False, "available": True, "disabled_reason": None,
            "schema": {"type": "object"}, "schema_hash": schema_hash}


def test_user_owned_connection_lifecycle_and_changed_schema(store, monkeypatch):
    monkeypatch.setenv("MAGI_MCP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    _, alice = actor(store, "mcp-alice")
    _, bob = actor(store, "mcp-bob")
    selected = [tool()]
    monkeypatch.setattr("backend.mcp_client.remote.catalog", lambda url, headers: [dict(t) for t in selected])
    service = MCPService(store)
    mark = ACTOR.set(alice)
    try:
        item = service.create(alice["id"], {"name": "문서", "url": "https://example.com/mcp", "auth_type": "none"})
        ident = item["id"]
        assert item["enabled"] is False and item["tools"] == []
        item = service.test(alice["id"], ident)
        assert item["status"] == "ready" and item["tools"][0]["enabled"] is False
        item = service.update(alice["id"], ident, {"selected_tools": ["find"], "enabled": True})
        assert item["enabled"] is True
        snapshot = service.snapshot(alice["id"])
        assert len(snapshot) == 1 and len(service.available(alice["id"], snapshot)) == 1
        selected[:] = [tool("v2")]
        changed = service.test(alice["id"], ident)
        assert changed["tools"][0]["schema_changed"] is True
        assert changed["tools"][0]["enabled"] is False and changed["enabled"] is False
        assert service.available(alice["id"], snapshot) == []
    finally:
        ACTOR.reset(mark)
    mark = ACTOR.set(bob)
    try:
        assert service.list(bob["id"])["connections"] == []
        with pytest.raises(AccessError):
            service.get(bob["id"], ident)
        with pytest.raises(AccessError):
            service.get(alice["id"], ident)
    finally:
        ACTOR.reset(mark)


def test_url_change_clears_credentials_and_old_snapshot(store, monkeypatch):
    monkeypatch.setenv("MAGI_MCP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    _, user = actor(store, "mcp-credentials")
    monkeypatch.setattr("backend.mcp_client.remote.catalog", lambda url, headers: [tool()])
    service = MCPService(store)
    mark = ACTOR.set(user)
    try:
        item = service.create(user["id"], {"name": "API", "url": "https://first.example/mcp",
            "auth_type": "api_key", "api_key_header": "X-API-Key", "credential": "fake-sensitive-value"})
        ident = item["id"]
        assert "fake-sensitive-value" not in json.dumps(item)
        service.test(user["id"], ident)
        service.update(user["id"], ident, {"selected_tools": ["find"], "enabled": True})
        snapshot = service.snapshot(user["id"])
        changed = service.update(user["id"], ident, {"url": "https://second.example/mcp"})
        assert changed["enabled"] is False and changed["has_credential"] is False
        assert service.available(user["id"], snapshot) == []
    finally:
        ACTOR.reset(mark)


def test_sensitive_create_idempotency_stores_only_hmac_and_safe_result(store, monkeypatch):
    monkeypatch.setenv("MAGI_MCP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    sid, user = actor(store, "mcp-idempotency")
    service = PublicService(SimpleNamespace(knowledge=SimpleNamespace(store=store)))
    request = {"method": "mcp.create", "session": sid, "csrf": user["csrf"], "idempotency_key": "operation-id-1",
               "params": {"name": "API", "url": "https://example.com/mcp", "auth_type": "bearer", "credential": "fake-sensitive-value"}}
    first = service.invoke(request, None)
    assert service.invoke(request, None)["id"] == first["id"]
    assert "fake-sensitive-value" not in json.dumps(first)
    with store.transaction(mode="read") as conn:
        receipt = conn.execute("SELECT fingerprint,result FROM admissions WHERE user_id=%s AND key=%s", (user["id"], "operation-id-1")).fetchone()
        assert "fake-sensitive-value" not in json.dumps(receipt)
    changed = {**request, "params": {**request["params"], "credential": "other-fake"}}
    with pytest.raises(AccessError):
        service.invoke(changed, None)


def test_remote_error_never_exposes_exception_content(monkeypatch, caplog):
    service = MCPService(object())
    row = {"url": "https://example.com/mcp", "auth_type": "none"}
    monkeypatch.setattr(service, "available", lambda *args: [(row, {"name": "find"})])
    row["id"] = "conn"
    def fail(*args):
        raise ValueError("fake-sensitive-sdk-exception")
    monkeypatch.setattr("backend.mcp_client.remote.invoke", fail)
    with pytest.raises(AccessError) as caught:
        service.invoke("owner", [], "conn", "find", {})
    assert "fake-sensitive-sdk-exception" not in str(caught.value)
    assert "fake-sensitive-sdk-exception" not in caplog.text
