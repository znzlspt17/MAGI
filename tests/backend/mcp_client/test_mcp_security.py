"""MCP 입력과 네트워크 경계는 외부 서버 없이 검증한다."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from mcp.types import Tool, ToolAnnotations

from backend.mcp_client.security import (
    BoundedStream, MCPValidationError, PublicNetworkBackend, public_url,
    validate_arguments, validate_schema,
)
from backend.mcp_client.secrets import seal, unseal
from backend.mcp_client.remote import catalog_tool


@pytest.mark.parametrize("url", [
    "http://example.com/mcp", "https://localhost/mcp", "https://127.0.0.1/mcp",
    "https://169.254.169.254/mcp", "https://[::1]/mcp", "https://user:pass@example.com/mcp",
    "https://example.com:0/mcp", "https://example.com:65536/mcp", "https://127.0.0.1:8443/mcp", "https://example.com/mcp#fragment",
    "https://[64:ff9b::7f00:1]/mcp", "https://[2002:7f00:1::]/mcp",
])
def test_rejects_nonpublic_and_non_https_urls(url):
    with pytest.raises(MCPValidationError):
        public_url(url)


def test_public_https_url_is_valid():
    assert public_url("https://example.com/mcp") == "https://example.com/mcp"
    assert public_url("https://example.com:8443/mcp") == "https://example.com:8443/mcp"


def test_dns_private_answer_rejected_before_connect(monkeypatch):
    async def resolve(*args, **kwargs):
        return [(2, 1, 6, "", ("127.0.0.1", 443))]
    monkeypatch.setattr("backend.mcp_client.security.anyio.getaddrinfo", resolve)
    backend = AsyncMock()
    with pytest.raises(MCPValidationError):
        asyncio.run(PublicNetworkBackend(backend).connect_tcp("example.com", 443))
    backend.connect_tcp.assert_not_called()


def test_dns_public_address_is_passed_directly_to_network(monkeypatch):
    async def resolve(*args, **kwargs):
        return [(2, 1, 6, "", ("8.8.8.8", 8443))]
    monkeypatch.setattr("backend.mcp_client.security.anyio.getaddrinfo", resolve)
    backend = AsyncMock()
    asyncio.run(PublicNetworkBackend(backend).connect_tcp("example.com", 8443))
    assert backend.connect_tcp.call_args.args[:2] == ("8.8.8.8", 8443)


@pytest.mark.parametrize("schema", [
    {"$ref": "https://example.com/schema"},
    {"$ref": "#/$defs/example"},
    {"properties": {"q": {"pattern": "(a+)+$"}}},
    {"patternProperties": {".*": {}}},
    {"$schema": "http://json-schema.org/draft-07/schema#"},
])
def test_untrusted_schema_is_rejected(schema):
    with pytest.raises(MCPValidationError):
        validate_schema(schema)


def test_arguments_validated_against_server_schema():
    schema = {"type": "object", "properties": {"query": {"type": "string"}},
              "required": ["query"], "additionalProperties": False}
    assert validate_arguments(schema, {"query": "hello"}) == {"query": "hello"}
    with pytest.raises(MCPValidationError):
        validate_arguments(schema, {"query": 1})


def test_ciphertext_is_bound_to_user_and_connection(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("MAGI_MCP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    ciphertext = seal("user1", "conn1", {"credential": "example"})
    assert "example" not in ciphertext
    assert unseal("user1", "conn1", ciphertext) == {"credential": "example"}
    with pytest.raises(ValueError):
        unseal("user2", "conn1", ciphertext)


def test_response_stream_has_byte_limit():
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"123"
            yield b"456"
        async def aclose(self):
            pass
    async def collect():
        return [part async for part in BoundedStream(Stream(), limit=4)]
    with pytest.raises(MCPValidationError):
        asyncio.run(collect())


def test_tool_catalog_requires_readonly_and_supported_schema():
    safe = Tool(name="search", description="Search", inputSchema={"type": "object"},
                annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    assert catalog_tool(safe)["available"] is True
    assert catalog_tool(safe.model_copy(update={"annotations": None}))["available"] is False
    unsupported = safe.model_copy(update={"inputSchema": {"$ref": "#/$defs/args"}})
    assert catalog_tool(unsupported)["available"] is False
    destructive = safe.model_copy(update={"annotations": ToolAnnotations(readOnlyHint=True, destructiveHint=True)})
    assert catalog_tool(destructive)["available"] is False


def test_tool_name_never_truncated_to_a_different_tool():
    tool = Tool(name="a" * 129, inputSchema={"type": "object"})
    with pytest.raises(MCPValidationError):
        catalog_tool(tool)
