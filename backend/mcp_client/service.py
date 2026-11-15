"""사용자 소유 MCP 연결과 도구 허용 상태."""

from __future__ import annotations

import json
import re
from uuid import uuid4

from backend.access.context import ACTOR, AccessError
from backend.access.ownership import can_access, owner_ids
from backend.mcp_client import remote
from backend.mcp_client.secrets import seal, unseal
from backend.mcp_client.security import MCPValidationError, public_url


_AUTH_TYPES = {"none", "api_key", "bearer", "oauth"}
_HEADER = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,63}$")
_UNSAFE_HEADERS = {"host", "connection", "cookie", "content-length", "transfer-encoding", "proxy-authorization"}


def _public(row):
    return {"id": row["id"], "name": row["name"], "url": row["url"], "auth_type": row["auth_type"],
            "enabled": row["enabled"], "status": row["status"], "has_credential": bool(row["secret_ciphertext"]),
            "oauth_client_id": row["oauth_client_id"], "api_key_header": row["api_key_header"], "error": None,
            "tools": [{key: item.get(key) for key in ("name", "description", "read_only_hint", "destructive_hint", "enabled", "schema_changed", "available", "disabled_reason")}
                      for item in row["tools"]]}


async def _row(conn, owner_id, ident, lock=False):
    row = (await (await conn.execute("SELECT * FROM mcp_connections WHERE owner_id=%s AND id=%s" + (" FOR UPDATE" if lock else ""),
                       (owner_id, ident))).fetchone())
    if not row:
        raise AccessError("MCP 연결을 찾을 수 없습니다.", "invalid")
    return row


def _check_input(data, *, create=False):
    if not isinstance(data, dict):
        raise AccessError("연결 정보를 확인하세요.", "invalid")
    allowed = {"name", "url", "auth_type", "api_key_header", "credential", "oauth_client_id", "oauth_client_secret", "enabled", "selected_tools"}
    if set(data) - allowed:
        raise AccessError("연결 정보를 확인하세요.", "invalid")
    if create and not {"name", "url", "auth_type"}.issubset(data):
        raise AccessError("연결 정보를 확인하세요.", "invalid")
    if "name" in data and (not isinstance(data["name"], str) or not 1 <= len(data["name"].strip()) <= 120):
        raise AccessError("연결 이름을 확인하세요.", "invalid")
    if "url" in data:
        try:
            public_url(data["url"])
            # 쿼리에는 인증정보가 들어갈 수 있으므로 설정 URL에서 허용하지 않는다.
            from urllib.parse import urlsplit
            if urlsplit(data["url"]).query:
                raise MCPValidationError("쿼리가 없는 주소가 필요합니다.")
        except MCPValidationError as exc:
            raise AccessError(str(exc), "invalid") from None
    if "auth_type" in data and data["auth_type"] not in _AUTH_TYPES:
        raise AccessError("인증 방식을 확인하세요.", "invalid")
    if "api_key_header" in data and data["api_key_header"] is not None:
        header = data["api_key_header"]
        if not isinstance(header, str) or not _HEADER.fullmatch(header) or header.lower() in _UNSAFE_HEADERS:
            raise AccessError("인증 헤더 이름을 확인하세요.", "invalid")
    for field in ("credential", "oauth_client_id", "oauth_client_secret"):
        if field in data and data[field] is not None and (not isinstance(data[field], str) or len(data[field]) > 4096 or "\r" in data[field] or "\n" in data[field]):
            raise AccessError("인증 정보를 확인하세요.", "invalid")
    if "enabled" in data and type(data["enabled"]) is not bool:
        raise AccessError("활성화 설정을 확인하세요.", "invalid")
    if "selected_tools" in data and (not isinstance(data["selected_tools"], list) or len(data["selected_tools"]) > 20
                                     or not all(isinstance(item, str) and len(item) <= 128 for item in data["selected_tools"])):
        raise AccessError("도구 선택을 확인하세요.", "invalid")


class MCPService:
    def __init__(self, store):
        self.store = store

    async def list(self, owner_id, owners=None):
        async with self.store.transaction(mode="read") as conn:
            rows = (await (await conn.execute("SELECT * FROM mcp_connections WHERE owner_id=ANY(%s) ORDER BY created_at,id", (list(owners or [owner_id]),))).fetchall())
            return {"connections": [_public(row) for row in rows]}

    async def connection_owner(self, owners, ident):
        # 2026-11-13: 암호문은 원래 소유자에 결합되어 있어 소유자를 이전하지 않는다.
        async with self.store.transaction(mode="read") as conn:
            row = await (await conn.execute(
                "SELECT owner_id FROM mcp_connections WHERE id=%s AND owner_id=ANY(%s)",
                (ident, list(owners)),
            )).fetchone()
        if not row:
            raise AccessError("MCP 연결을 찾을 수 없습니다.", "invalid")
        return row['owner_id']

    async def snapshot(self, owners):
        """새 작업에 허용 도구만 고정하며 인증정보를 포함하지 않는다."""
        owners = [owners] if isinstance(owners, str) else list(owners)
        async with self.store.transaction(mode="read") as conn:
            rows = (await (await conn.execute("SELECT * FROM mcp_connections WHERE owner_id=ANY(%s) AND enabled=true AND status='ready' ORDER BY created_at,id", (owners,))).fetchall())
            result = [{"connection_id": row["id"], "connection_version": row["version"], "name": tool["name"], "schema_hash": tool["schema_hash"]}
                      for row in rows for tool in row["tools"] if tool.get("enabled") and tool.get("available")]
            if len(result) > 20:
                raise AccessError("활성화된 MCP 도구가 20개를 초과합니다. 연결 설정을 조정하세요.", "invalid")
            return result

    async def available(self, owner_id, snapshot):
        actor = ACTOR.get()
        if actor is not None and not can_access(actor, owner_id):
            raise AccessError("MCP 연결을 찾을 수 없습니다.", "invalid")
        owners = list(owner_ids(actor)) if actor else [owner_id]
        async with self.store.transaction(mode="read") as conn:
            rows = (await (await conn.execute("SELECT * FROM mcp_connections WHERE owner_id=ANY(%s) AND enabled=true AND status='ready'", (owners,))).fetchall())
        allowed = {(entry.get("connection_id"), entry.get("connection_version"), entry.get("name"), entry.get("schema_hash")) for entry in snapshot}
        return [(row, tool) for row in rows for tool in row["tools"]
                if tool.get("enabled") and tool.get("available") and
                (row["id"], row["version"], tool.get("name"), tool.get("schema_hash")) in allowed]

    async def invoke(self, owner_id, snapshot, connection_id, name, arguments):
        selected = next(((row, tool) for row, tool in (await self.available(owner_id, snapshot))
                         if row["id"] == connection_id and tool["name"] == name), None)
        if selected is None:
            raise MCPValidationError("현재 작업에서 허용되지 않은 도구입니다.")
        row, tool = selected
        headers = (await self.headers(row))
        try:
            return (await remote.invoke(row["url"], headers, tool, arguments))
        except Exception:
            # 원격 예외에는 인증값·도구 입력이 포함될 수 있어 유출하지 않는다.
            raise AccessError("MCP 도구 실행 완료 여부를 확인할 수 없습니다.", "unavailable") from None

    async def get(self, owner_id, ident):
        async with self.store.transaction(mode="read") as conn:
            return _public((await _row(conn, owner_id, ident)))

    async def create(self, owner_id, data):
        _check_input(data, create=True)
        if data.get("enabled") or data.get("selected_tools"):
            raise AccessError("연결을 시험하고 도구를 선택한 후 활성화하세요.", "invalid")
        ident = uuid4().hex
        secrets = {key: data[key] for key in ("credential", "oauth_client_secret") if data.get(key)}
        encrypted = seal(owner_id, ident, secrets) if secrets else None
        async with self.store.transaction() as conn:
            (await conn.execute("INSERT INTO mcp_connections(id,owner_id,name,url,auth_type,api_key_header,oauth_client_id,secret_ciphertext) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (ident, owner_id, data["name"].strip(), data["url"], data["auth_type"], data.get("api_key_header"), data.get("oauth_client_id"), encrypted)))
            return _public((await _row(conn, owner_id, ident)))

    async def update(self, owner_id, ident, data):
        _check_input(data)
        async with self.store.transaction() as conn:
            row = (await _row(conn, owner_id, ident, lock=True))
            changing_connection = any(key in data and data[key] != row[key] for key in ("url", "auth_type", "api_key_header", "oauth_client_id"))
            has_new_secrets = any(data.get(key) for key in ("credential", "oauth_client_secret"))
            secrets = unseal(owner_id, ident, row["secret_ciphertext"]) if row["secret_ciphertext"] else {}
            # 2026-11-03: 인증 대상을 바꿀 때 기존 비밀을 새 서버로 전달하지 않는다.
            if changing_connection:
                secrets = {}
            for key in ("credential", "oauth_client_secret"):
                if data.get(key):
                    secrets[key] = data[key]
            tools = [] if changing_connection or has_new_secrets else row["tools"]
            if "selected_tools" in data:
                selected = set(data["selected_tools"])
                eligible = {item["name"] for item in tools if item.get("available")}
                if not selected <= eligible:
                    raise AccessError("선택할 수 없는 도구가 있습니다.", "invalid")
                tools = [{**item, "enabled": item["name"] in selected, "schema_changed": False if item["name"] in selected else item.get("schema_changed", False)} for item in tools]
            enabled = data.get("enabled", row["enabled"])
            if changing_connection or has_new_secrets:
                enabled = False
            status = "disconnected" if changing_connection or has_new_secrets else row["status"]
            if enabled and (status != "ready" or not any(item.get("enabled") for item in tools)):
                raise AccessError("연결을 시험하고 도구를 선택한 후 활성화하세요.", "invalid")
            if enabled:
                others = (await (await conn.execute("SELECT tools FROM mcp_connections WHERE owner_id=%s AND id<>%s AND enabled=true AND status='ready'", (owner_id, ident))).fetchall())
                total = sum(bool(item.get("enabled")) for other in others for item in other["tools"])
                total += sum(bool(item.get("enabled")) for item in tools)
                if total > 20:
                    raise AccessError("활성화된 MCP 도구는 총 20개까지 허용됩니다.", "invalid")
            encrypted = seal(owner_id, ident, secrets) if secrets else None
            (await conn.execute("UPDATE mcp_connections SET name=%s,url=%s,auth_type=%s,api_key_header=%s,oauth_client_id=%s,secret_ciphertext=%s,enabled=%s,status=%s,tools=%s,version=version+1,updated_at=now() WHERE id=%s AND owner_id=%s",
                (data.get("name", row["name"]).strip(), data.get("url", row["url"]), data.get("auth_type", row["auth_type"]),
                 data.get("api_key_header", row["api_key_header"]), data.get("oauth_client_id", row["oauth_client_id"]), encrypted,
                 enabled, status, self.store._json(tools), ident, owner_id)))
            return _public((await _row(conn, owner_id, ident)))

    async def delete(self, owner_id, ident):
        async with self.store.transaction() as conn:
            (await _row(conn, owner_id, ident, lock=True))
            (await conn.execute("DELETE FROM mcp_connections WHERE id=%s AND owner_id=%s", (ident, owner_id)))
        return {"ok": True}

    async def headers(self, row):
        kind = row["auth_type"]
        if kind == "none":
            return {}
        secrets = unseal(row["owner_id"], row["id"], row["secret_ciphertext"])
        if kind == "oauth":
            from backend.mcp_client.oauth import token
            value = (await token(self.store, row["owner_id"], row["id"],
                          expected_version=row["version"], expected_resource=row["url"]))
            return {"Authorization": "Bearer " + value}
        value = secrets.get("credential")
        if not value:
            raise AccessError("MCP 인증 설정이 필요합니다.", "unavailable")
        if kind == "bearer":
            return {"Authorization": "Bearer " + value}
        if not row["api_key_header"]:
            raise AccessError("인증 헤더 이름이 필요합니다.", "invalid")
        return {row["api_key_header"]: value}

    async def test(self, owner_id, ident):
        async with self.store.transaction(mode="read") as conn:
            row = (await _row(conn, owner_id, ident))
        try:
            headers = (await self.headers(row))
            found = (await remote.catalog(row["url"], headers))
        except Exception as exc:
            status = "auth_required" if isinstance(exc, AccessError) else "error"
            async with self.store.transaction() as conn:
                current = (await _row(conn, owner_id, ident, lock=True))
                if current["version"] == row["version"]:
                    (await conn.execute("UPDATE mcp_connections SET status=%s,enabled=false,version=version+1,updated_at=now() WHERE id=%s AND owner_id=%s",
                                 (status, ident, owner_id)))
            if isinstance(exc, AccessError):
                raise
            raise AccessError("MCP 서버에 연결하거나 도구 목록을 읽을 수 없습니다.", "unavailable") from None
        async with self.store.transaction() as conn:
            current = (await _row(conn, owner_id, ident, lock=True))
            if current["version"] != row["version"]:
                raise AccessError("연결 설정이 변경되었습니다. 다시 시험하세요.", "busy")
            previous = {item["name"]: item for item in current["tools"]}
            for item in found:
                prior = previous.get(item["name"], {})
                changed = bool(prior and (prior.get("schema_hash") != item["schema_hash"]
                         or prior.get("read_only_hint") != item["read_only_hint"]
                         or prior.get("destructive_hint") != item["destructive_hint"]))
                item["schema_changed"] = changed or bool(prior.get("schema_changed"))
                item["enabled"] = bool(prior.get("enabled") and item["available"] and not changed)
            enabled = bool(current["enabled"] and any(item["enabled"] for item in found))
            (await conn.execute("UPDATE mcp_connections SET tools=%s,status='ready',enabled=%s,version=version+1,updated_at=now() WHERE owner_id=%s AND id=%s",
                         (self.store._json(found), enabled, owner_id, ident)))
            return _public((await _row(conn, owner_id, ident)))
