"""사용자별 연결과 중복 방지 경계를 테스트 저장소에서 검증한다."""

import json
from unittest.mock import AsyncMock
from tests.backend.application.async_helpers import run_async
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from backend.access.context import ACTOR, AccessError
from backend.access.service import PublicService
from backend.access.store import AccessStore
from backend.mcp_client.service import MCPService


async def actor(store, name):
    access = AccessStore(store)
    sid = (await access.login(name, "fake-test-pepper"))
    return sid, (await access.session(sid))


def tool(schema_hash="v1"):
    return {"name": "find", "description": "문서 검색", "read_only_hint": True,
            "destructive_hint": False, "available": True, "disabled_reason": None,
            "schema": {"type": "object"}, "schema_hash": schema_hash}


@run_async
async def test_user_owned_connection_lifecycle_and_changed_schema(async_store_factory, monkeypatch):
    async with async_store_factory() as store:
        monkeypatch.setenv("MAGI_MCP_ENCRYPTION_KEY", Fernet.generate_key().decode())
        _, alice = (await actor(store, "mcp-alice"))
        _, bob = (await actor(store, "mcp-bob"))
        selected = [tool()]
        monkeypatch.setattr("backend.mcp_client.remote.catalog", AsyncMock(side_effect=lambda url, headers: [dict(t) for t in selected]))
        service = MCPService(store)
        mark = ACTOR.set(alice)
        try:
            item = (await service.create(alice["id"], {"name": "문서", "url": "https://example.com/mcp", "auth_type": "none"}))
            ident = item["id"]
            assert item["enabled"] is False and item["tools"] == []
            item = (await service.test(alice["id"], ident))
            assert item["status"] == "ready" and item["tools"][0]["enabled"] is False
            item = (await service.update(alice["id"], ident, {"selected_tools": ["find"], "enabled": True}))
            assert item["enabled"] is True
            snapshot = (await service.snapshot(alice["id"]))
            assert len(snapshot) == 1 and len((await service.available(alice["id"], snapshot))) == 1
            selected[:] = [tool("v2")]
            changed = (await service.test(alice["id"], ident))
            assert changed["tools"][0]["schema_changed"] is True
            assert changed["tools"][0]["enabled"] is False and changed["enabled"] is False
            assert (await service.available(alice["id"], snapshot)) == []
        finally:
            ACTOR.reset(mark)
        mark = ACTOR.set(bob)
        try:
            assert (await service.list(bob["id"]))["connections"] == []
            with pytest.raises(AccessError):
                (await service.get(bob["id"], ident))
            with pytest.raises(AccessError):
                (await service.get(alice["id"], ident))
        finally:
            ACTOR.reset(mark)


@run_async
async def test_url_change_clears_credentials_and_old_snapshot(async_store_factory, monkeypatch):
    async with async_store_factory() as store:
        monkeypatch.setenv("MAGI_MCP_ENCRYPTION_KEY", Fernet.generate_key().decode())
        _, user = (await actor(store, "mcp-credentials"))
        monkeypatch.setattr("backend.mcp_client.remote.catalog", AsyncMock(return_value=[tool()]))
        service = MCPService(store)
        mark = ACTOR.set(user)
        try:
            item = (await service.create(user["id"], {"name": "API", "url": "https://first.example/mcp",
                "auth_type": "api_key", "api_key_header": "X-API-Key", "credential": "fake-sensitive-value"}))
            ident = item["id"]
            assert "fake-sensitive-value" not in json.dumps(item)
            (await service.test(user["id"], ident))
            (await service.update(user["id"], ident, {"selected_tools": ["find"], "enabled": True}))
            snapshot = (await service.snapshot(user["id"]))
            changed = (await service.update(user["id"], ident, {"url": "https://second.example/mcp"}))
            assert changed["enabled"] is False and changed["has_credential"] is False
            assert (await service.available(user["id"], snapshot)) == []
        finally:
            ACTOR.reset(mark)


@run_async
async def test_sensitive_create_idempotency_stores_only_hmac_and_safe_result(async_store_factory, monkeypatch):
    async with async_store_factory() as store:
        monkeypatch.setenv("MAGI_MCP_ENCRYPTION_KEY", Fernet.generate_key().decode())
        sid, user = (await actor(store, "mcp-idempotency"))
        service = PublicService(SimpleNamespace(knowledge=SimpleNamespace(store=store)))
        request = {"method": "mcp.create", "session": sid, "csrf": user["csrf"], "idempotency_key": "operation-id-1",
                   "params": {"name": "API", "url": "https://example.com/mcp", "auth_type": "bearer", "credential": "fake-sensitive-value"}}
        first = (await service.invoke(request, None))
        assert (await service.invoke(request, None))["id"] == first["id"]
        assert "fake-sensitive-value" not in json.dumps(first)
        async with store.transaction(mode="read") as conn:
            receipt = (await (await conn.execute("SELECT fingerprint,result FROM admissions WHERE user_id=%s AND key=%s", (user["id"], "operation-id-1"))).fetchone())
            assert "fake-sensitive-value" not in json.dumps(receipt)
        changed = {**request, "params": {**request["params"], "credential": "other-fake"}}
        with pytest.raises(AccessError):
            (await service.invoke(changed, None))


@run_async
async def test_remote_error_never_exposes_exception_content(monkeypatch, caplog):
    service = MCPService(object())
    row = {"url": "https://example.com/mcp", "auth_type": "none"}
    monkeypatch.setattr(service, "available", AsyncMock(return_value=[(row, {"name": "find"})]))
    row["id"] = "conn"
    async def fail(*args):
        raise ValueError("fake-sensitive-sdk-exception")
    monkeypatch.setattr("backend.mcp_client.remote.invoke", fail)
    with pytest.raises(AccessError) as caught:
        (await service.invoke("owner", [], "conn", "find", {}))
    assert "fake-sensitive-sdk-exception" not in str(caught.value)
    assert "fake-sensitive-sdk-exception" not in caplog.text
