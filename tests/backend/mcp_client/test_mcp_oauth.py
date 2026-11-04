"""MCP OAuth의 경계는 외부 인증 서버 없이 가짜 응답으로 검증한다."""

import asyncio
import base64
import hashlib
from contextlib import contextmanager
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet

from backend.access.context import AccessError
from backend.mcp_client import oauth
from backend.mcp_client.secrets import seal, unseal


OWNER, CONNECTION, SID = "user-a", "mcp-a", "test-session-a"
ORIGIN, RESOURCE = "https://magi.example", "https://mcp.example/mcp"


class Result:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class MemoryStore:
    def __init__(self):
        self.connection = {"id": CONNECTION, "owner_id": OWNER, "auth_type": "oauth",
                           "url": RESOURCE, "version": 1, "oauth_client_id": "test-client",
                           "secret_ciphertext": None, "status": "disconnected", "enabled": False}
        self.states = {}
        self.refresh = False

    @contextmanager
    def transaction(self, **kwargs):
        yield self

    def execute(self, sql, params=()):
        if sql.startswith("SELECT * FROM mcp_connections"):
            owner, ident = params
            return Result(dict(self.connection) if (owner, ident) == (OWNER, CONNECTION) else None)
        if sql.startswith("DELETE FROM mcp_oauth_states WHERE state_hash"):
            hashed, owner, session, now = params
            state = self.states.get(hashed)
            if not state or state["owner_id"] != owner or state["session_hash"] != session or state["expires_at"] <= now:
                return Result()
            self.states.pop(hashed)
            return Result(state)
        if sql.startswith("DELETE FROM mcp_oauth_states"):
            self.states.clear()
            return Result()
        if sql.startswith("INSERT INTO mcp_oauth_states"):
            hashed, owner, ident, session, expires, payload = params
            self.states[hashed] = {"owner_id": owner, "connection_id": ident, "session_hash": session,
                                   "expires_at": expires, "payload_ciphertext": payload}
            return Result()
        if sql.startswith("INSERT INTO mcp_oauth_refreshes"):
            if self.refresh:
                return Result()
            self.refresh = True
            return Result({"connection_id": CONNECTION})
        if sql.startswith("DELETE FROM mcp_oauth_refreshes"):
            self.refresh = False
            return Result()
        if "SET version=version+1,status='auth_required'" in sql:
            self.connection.update(version=self.connection["version"] + 1, status="auth_required", enabled=False)
            return Result()
        if "SET secret_ciphertext=%s,status='disconnected'" in sql:
            self.connection.update(secret_ciphertext=params[0], status="disconnected", enabled=False)
            return Result()
        if "SET secret_ciphertext=%s,updated_at" in sql:
            self.connection["secret_ciphertext"] = params[0]
            return Result()
        if "SET status='auth_required'" in sql:
            self.connection.update(status="auth_required", enabled=False)
            return Result()
        raise AssertionError(sql)


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setenv("MAGI_MCP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    return MemoryStore()


@pytest.fixture
def discovery(monkeypatch):
    async def prepare(row, saved, origin):
        return ({"issuer": "https://auth.example", "authorization_endpoint": "https://auth.example/authorize",
                 "token_endpoint": "https://auth.example/token"},
                {"client_id": "test-client", "client_secret": None, "method": "none"}, "docs.read")
    monkeypatch.setattr(oauth, "_prepare", prepare)


def begin(store):
    url = oauth.begin(store, OWNER, CONNECTION, SID, ORIGIN)["url"]
    return parse_qs(urlsplit(url).query)


def test_oauth_authorize_dns_uses_explicit_https_port(monkeypatch):
    async def discover(client, resource):
        return ({}, {"issuer": "https://auth.example:8443", "authorization_endpoint": "https://auth.example:8443/authorize",
                     "token_endpoint": "https://auth.example:8443/token"}, {})
    async def select(*args):
        return {"client_id": "fake"}
    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
    observed = []
    async def resolve(host, port, **kwargs):
        observed.append((host, port))
        return [(2, 1, 6, "", ("8.8.8.8", port))]
    monkeypatch.setattr(oauth, "_discover", discover)
    monkeypatch.setattr(oauth, "_select_client", select)
    monkeypatch.setattr(oauth, "public_client", lambda: Client())
    monkeypatch.setattr(oauth.anyio, "getaddrinfo", resolve)
    asyncio.run(oauth._prepare({"url": RESOURCE}, {}, ORIGIN))
    assert observed == [("auth.example", 8443)]


def test_state_pkce_and_session_binding(store, discovery, monkeypatch):
    params = begin(store)
    assert params["code_challenge_method"] == ["S256"]
    assert params["resource"] == [RESOURCE]
    state = params["state"][0]
    saved = next(iter(store.states.values()))
    assert state not in str(saved) and SID not in str(saved)
    exchange = []

    async def fake_exchange(grant, fields):
        exchange.append(fields)
        return {"access_token": "fake-access", "refresh_token": "fake-refresh", "expires_at": 9999999999}
    monkeypatch.setattr(oauth, "_exchange", fake_exchange)
    with pytest.raises(AccessError):
        oauth.callback(store, OWNER, "wrong-session", state, "fake-code", ORIGIN)
    assert not exchange
    oauth.callback(store, OWNER, SID, state, "fake-code", ORIGIN)
    assert exchange[0]["code_verifier"]
    expected = base64.urlsafe_b64encode(hashlib.sha256(exchange[0]["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert params["code_challenge"] == [expected]
    tokens = unseal(OWNER, CONNECTION, store.connection["secret_ciphertext"])["oauth_tokens"]
    assert tokens["access_token"] == "fake-access"
    assert "fake-access" not in store.connection["secret_ciphertext"]
    with pytest.raises(AccessError):
        oauth.callback(store, OWNER, SID, state, "fake-code", ORIGIN)
    assert len(exchange) == 1


def test_expired_state_and_changed_connection_fail_before_token_request(store, discovery, monkeypatch):
    params = begin(store)
    next(iter(store.states.values()))["expires_at"] = 0
    with pytest.raises(AccessError):
        oauth.callback(store, OWNER, SID, params["state"][0], "fake-code", ORIGIN)
    params = begin(store)
    store.connection["version"] += 1
    called = []
    async def no_exchange(*args):
        called.append(True)
    monkeypatch.setattr(oauth, "_exchange", no_exchange)
    with pytest.raises(AccessError):
        oauth.callback(store, OWNER, SID, params["state"][0], "fake-code", ORIGIN)
    assert not called


def test_token_refresh_rotation_and_pending_uncertainty(store, monkeypatch):
    grant = {"resource": RESOURCE, "issuer": "https://auth.example", "token_endpoint": "https://auth.example/token",
             "client": {"client_id": "test-client", "client_secret": None}}
    store.connection["secret_ciphertext"] = seal(OWNER, CONNECTION, {"oauth_grant": grant,
        "oauth_tokens": {"access_token": "expired", "refresh_token": "old", "expires_at": 1}})
    async def exchange(g, data):
        assert data["refresh_token"] == "old"
        return {"access_token": "fresh", "refresh_token": "rotated", "expires_at": 9999999999}
    monkeypatch.setattr(oauth, "_exchange", exchange)
    assert oauth.token(store, OWNER, CONNECTION, expected_version=1, expected_resource=RESOURCE) == "fresh"
    assert unseal(OWNER, CONNECTION, store.connection["secret_ciphertext"])["oauth_tokens"]["refresh_token"] == "rotated"
    assert not store.refresh
    saved = unseal(OWNER, CONNECTION, store.connection["secret_ciphertext"])
    saved["oauth_tokens"]["expires_at"] = 1
    store.connection["secret_ciphertext"] = seal(OWNER, CONNECTION, saved)
    store.refresh = True
    with pytest.raises(AccessError):
        oauth.token(store, OWNER, CONNECTION, expected_version=1, expected_resource=RESOURCE)


@pytest.mark.parametrize("expires_at", [1, 9999999999])
def test_stale_connection_never_sends_new_resource_token(store, monkeypatch, expires_at):
    from unittest.mock import Mock
    from backend.mcp_client.service import MCPService

    stale = dict(store.connection)
    stale["secret_ciphertext"] = seal(OWNER, CONNECTION, {"credential": "old-placeholder"})
    new_resource = "https://new.example/mcp"
    store.connection.update(version=2, url=new_resource, secret_ciphertext=seal(OWNER, CONNECTION, {
        "oauth_grant": {"resource": new_resource, "client": {"client_id": "fake"}},
        "oauth_tokens": {"access_token": "new-fake-token", "refresh_token": "new-fake-refresh", "expires_at": expires_at}}))
    service = MCPService(store)
    monkeypatch.setattr(service, "available", lambda *_: [(stale, {"name": "find"})])
    network = Mock()
    monkeypatch.setattr("backend.mcp_client.remote.invoke", network)
    with pytest.raises(AccessError, match="변경"):
        service.invoke(OWNER, [], CONNECTION, "find", {})
    network.assert_not_called()
    assert not store.refresh


def test_refresh_failure_disables_connection_and_retains_reservation(store, monkeypatch):
    grant = {"resource": RESOURCE, "token_endpoint": "https://auth.example/token", "client": {"client_id": "test"}}
    store.connection.update(enabled=True, status="ready", secret_ciphertext=seal(OWNER, CONNECTION,
        {"oauth_grant": grant, "oauth_tokens": {"access_token": "old", "refresh_token": "old", "expires_at": 1}}))
    async def fail(*args):
        raise OSError("network")
    monkeypatch.setattr(oauth, "_exchange", fail)
    with pytest.raises(AccessError):
        oauth.token(store, OWNER, CONNECTION, expected_version=1, expected_resource=RESOURCE)
    assert store.connection["status"] == "auth_required" and not store.connection["enabled"]
    assert store.refresh


class FakeClient:
    def __init__(self, responses):
        self.responses, self.requests = responses, []

    async def get(self, url, **kwargs):
        return await self.request("GET", url, **kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        status, body, headers = self.responses[(method, url)]
        return httpx.Response(status, json=body, headers=headers, request=httpx.Request(method, url))


def test_resource_and_issuer_discovery_and_mismatch():
    client = FakeClient({
        ("GET", RESOURCE): (401, {}, {"www-authenticate": 'Bearer resource_metadata="https://mcp.example/meta", scope="docs.read"'}),
        ("GET", "https://mcp.example/meta"): (200, {"resource": RESOURCE, "authorization_servers": ["https://auth.example"]}, {}),
        ("GET", "https://auth.example/.well-known/oauth-authorization-server"): (200, {"issuer": "https://auth.example", "authorization_endpoint": "https://auth.example/authorize", "token_endpoint": "https://auth.example/token"}, {}),
    })
    metadata, authorization, challenge = asyncio.run(oauth._discover(client, RESOURCE))
    assert metadata["resource"] == RESOURCE and authorization["issuer"] == "https://auth.example"
    assert challenge["scope"] == "docs.read"
    client.responses[("GET", "https://mcp.example/meta")] = (200, {"resource": "https://other.example", "authorization_servers": ["https://auth.example"]}, {})
    with pytest.raises(AccessError):
        asyncio.run(oauth._discover(client, RESOURCE))
    client.responses[("GET", "https://mcp.example/meta")] = (200, {"resource": RESOURCE, "authorization_servers": ["https://auth.example"]}, {})
    client.responses[("GET", "https://auth.example/.well-known/oauth-authorization-server")] = (200, {"issuer": "https://other.example", "authorization_endpoint": "https://auth.example/authorize", "token_endpoint": "https://auth.example/token"}, {})
    with pytest.raises(AccessError):
        asyncio.run(oauth._discover(client, RESOURCE))


def test_registration_selection_cimd_preregister_and_dynamic():
    registration = "https://auth.example/register"
    client = FakeClient({("POST", registration): (201, {"client_id": "dynamic", "token_endpoint_auth_method": "none"}, {})})
    row = {"oauth_client_id": "provided"}
    assert asyncio.run(oauth._select_client(client, row, {}, ORIGIN, {}))["client_id"] == "provided"
    row["oauth_client_id"] = None
    selected = asyncio.run(oauth._select_client(client, row, {}, ORIGIN, {"client_id_metadata_document_supported": True}))
    assert selected["client_id"] == ORIGIN + "/oauth/mcp-client-metadata.json"
    selected = asyncio.run(oauth._select_client(client, row, {}, ORIGIN, {"registration_endpoint": registration}))
    assert selected["client_id"] == "dynamic"


def test_private_issuer_rejected_before_metadata_fetch():
    client = FakeClient({
        ("GET", RESOURCE): (401, {}, {"www-authenticate": 'Bearer resource_metadata="https://mcp.example/meta"'}),
        ("GET", "https://mcp.example/meta"): (200, {"resource": RESOURCE, "authorization_servers": ["https://127.0.0.1"]}, {}),
    })
    with pytest.raises(ValueError):
        asyncio.run(oauth._discover(client, RESOURCE))
    assert len(client.requests) == 2


def test_token_exchange_confidential_client_and_invalid_token_type(monkeypatch):
    endpoint = "https://auth.example/token"
    client = FakeClient({("POST", endpoint): (200, {"access_token": "sample", "token_type": "Bearer", "expires_in": 3600}, {})})
    monkeypatch.setattr(oauth, "public_client", lambda: client)
    grant = {"resource": RESOURCE, "token_endpoint": endpoint,
             "client": {"client_id": "client:id", "client_secret": "fake:secret", "method": "client_secret_basic"}}
    result = asyncio.run(oauth._exchange(grant, {"grant_type": "authorization_code", "code": "sample-code"}))
    assert result["access_token"] == "sample"
    assert client.requests[0][2]["auth"] == ("client%3Aid", "fake%3Asecret")
    assert client.requests[0][2]["data"]["resource"] == RESOURCE
    client.responses[("POST", endpoint)] = (200, {"access_token": "sample", "token_type": "unknown"}, {})
    with pytest.raises(AccessError):
        asyncio.run(oauth._exchange(grant, {"grant_type": "authorization_code", "code": "sample-code"}))


def test_no_refresh_token_marks_connection_unavailable(store):
    grant = {"resource": RESOURCE}
    store.connection.update(status="ready", enabled=True, secret_ciphertext=seal(OWNER, CONNECTION,
        {"oauth_grant": grant, "oauth_tokens": {"access_token": "old", "refresh_token": None, "expires_at": 1}}))
    with pytest.raises(AccessError):
        oauth.token(store, OWNER, CONNECTION, expected_version=1, expected_resource=RESOURCE)
    assert store.connection["status"] == "auth_required" and not store.connection["enabled"]
