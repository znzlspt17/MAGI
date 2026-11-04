"""공식 MCP SDK 메시지 교환은 모의 HTTP 전송으로 검증한다."""

import json

import httpx

from backend.mcp_client import remote


def test_streamable_http_catalog_and_call_with_real_sdk(monkeypatch):
    calls = []
    tool = {"name": "find", "description": "find document", "inputSchema": {
        "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        "annotations": {"readOnlyHint": True, "destructiveHint": False}}

    def handle(request):
        if request.method in {"GET", "DELETE"}:
            return httpx.Response(405, request=request)
        message = json.loads(request.content)
        method = message.get("method")
        calls.append(method)
        if "id" not in message:
            return httpx.Response(202, request=request)
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "fake", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [tool]}
        elif method == "tools/call":
            assert message["params"] == {"name": "find", "arguments": {"query": "hello"}}
            result = {"content": [{"type": "text", "text": "documentation"}], "isError": False}
        else:
            raise AssertionError(method)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result}, request=request)

    monkeypatch.setattr(remote, "public_client", lambda headers=None: httpx.AsyncClient(
        transport=httpx.MockTransport(handle), headers=headers, timeout=30))
    tools = remote.catalog("https://example.com/mcp", {})
    assert len(tools) == 1 and tools[0]["available"] is True
    result = remote.invoke("https://example.com/mcp", {}, tools[0], {"query": "hello"})
    assert result == {"status": "ok", "text": "documentation"}
    assert calls.count("initialize") == 2
    assert calls.count("tools/list") == 2
    assert calls.count("tools/call") == 1
