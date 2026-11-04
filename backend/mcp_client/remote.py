"""별도 프로세스 없이 원격 Streamable HTTP MCP를 호출한다."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import hashlib
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from backend.mcp_client.security import MCPValidationError, public_client, public_url, validate_arguments, validate_schema


def _schema_hash(schema):
    return hashlib.sha256(json.dumps(schema, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def catalog_tool(tool):
    """2026-11-03: 서버의 선언을 사용자 허용과 함께 요구하되 안전 보증으로 취급하지 않는다."""
    annotations = tool.annotations
    read_only = bool(annotations and annotations.readOnlyHint is True)
    destructive = bool(annotations and annotations.destructiveHint is True)
    schema = tool.inputSchema
    try:
        validate_schema(schema)
        valid = True
    except MCPValidationError:
        valid = False
    reason = ("조회 전용으로 선언되지 않은 도구입니다." if not read_only else
              "변경 작업을 수행할 수 있는 도구입니다." if destructive else
              "지원하지 않는 입력 스키마입니다." if not valid else None)
    if len(tool.name) > 128 or not tool.name:
        raise MCPValidationError("도구 이름을 확인할 수 없습니다.")
    return {
        "name": tool.name, "description": (tool.description or "")[:2000],
        "read_only_hint": read_only, "destructive_hint": destructive,
        "schema": schema if valid else {}, "schema_hash": _schema_hash(schema),
        "available": read_only and not destructive and valid, "disabled_reason": reason,
    }


async def _catalog(url, headers):
    public_url(url)
    async with public_client(headers=headers) as client:
        async with streamable_http_client(url, http_client=client) as (read, write, _):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as session:
                await session.initialize()
                tools, cursor = [], None
                seen = set()
                for _ in range(10):
                    result = await session.list_tools(cursor=cursor)
                    tools.extend(catalog_tool(tool) for tool in result.tools)
                    if len(tools) > 100:
                        raise MCPValidationError("서버의 도구가 너무 많습니다.")
                    cursor = result.nextCursor
                    if not cursor:
                        break
                    if cursor in seen:
                        raise MCPValidationError("도구 목록을 확인할 수 없습니다.")
                    seen.add(cursor)
                else:
                    raise MCPValidationError("서버의 도구 목록이 너무 큽니다.")
                if len({tool["name"] for tool in tools}) != len(tools):
                    raise MCPValidationError("중복된 도구 이름이 있습니다.")
                return tools


async def _invoke(url, headers, expected, arguments):
    public_url(url)
    validate_arguments(expected["schema"], arguments)
    async with public_client(headers=headers) as client:
        async with streamable_http_client(url, http_client=client) as (read, write, _):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as session:
                await session.initialize()
                # 실행 직전에 서버의 도구 정의가 승인된 값과 같은지 재검증한다.
                cursor = None
                current = None
                for _ in range(10):
                    page = await session.list_tools(cursor=cursor)
                    current = next((catalog_tool(t) for t in page.tools if t.name == expected["name"]), None)
                    if current or not page.nextCursor:
                        break
                    cursor = page.nextCursor
                if not current or not current["available"] or current["schema_hash"] != expected["schema_hash"]:
                    raise MCPValidationError("도구가 변경되어 다시 허용해야 합니다.")
                result = await session.call_tool(expected["name"], arguments, read_timeout_seconds=timedelta(seconds=30))
                if result.isError:
                    return {"status": "error", "text": "도구 실행에 실패했습니다."}
                parts = [item.text for item in result.content if getattr(item, "type", None) == "text"]
                if result.structuredContent is not None:
                    parts.append(json.dumps(result.structuredContent, ensure_ascii=False))
                return {"status": "ok", "text": "\n".join(parts)[:8000]}


def catalog(url, headers):
    return asyncio.run(asyncio.wait_for(_catalog(url, headers), timeout=30))


def invoke(url, headers, expected, arguments):
    return asyncio.run(asyncio.wait_for(_invoke(url, headers, expected, arguments), timeout=30))
