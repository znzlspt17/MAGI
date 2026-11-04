"""사용자별 MCP OAuth를 작업 대화와 분리해 처리한다."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import re
import secrets
import time
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

import anyio

from backend.access.context import AccessError
from backend.mcp_client.security import is_public_ip, public_client, public_url
from backend.mcp_client.secrets import seal, unseal

_STATE_LIFETIME = 300
_REQUEST_TIMEOUT = 30


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _row(conn, owner, ident, *, lock=False):
    row = conn.execute(
        "SELECT * FROM mcp_connections WHERE owner_id=%s AND id=%s" + (" FOR UPDATE" if lock else ""),
        (owner, ident),
    ).fetchone()
    if not row or row["auth_type"] != "oauth":
        raise AccessError("MCP OAuth 연결을 찾을 수 없습니다.", "invalid")
    return row


def _base(value):
    parsed = urlsplit(public_url(value))
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _well_known(issuer, kind):
    parsed = urlsplit(public_url(issuer))
    path = parsed.path.rstrip("/")
    return _base(issuer) + "/.well-known/" + kind + path


def _challenge(value):
    # 2026-11-03: 서버 헤더는 비신뢰 입력이며 필요한 RFC 6750 인자만 읽는다.
    if not isinstance(value, str) or len(value) > 8192:
        return {}
    result = {}
    for match in re.finditer(r'(resource_metadata|scope)\s*=\s*"([^"\\\r\n]*)"', value, re.I):
        result[match.group(1).lower()] = match.group(2)
    return result


async def _json_request(client, method, url, **kwargs):
    public_url(url)
    response = await client.request(method, url, **kwargs)
    if response.status_code >= 400:
        return response.status_code, None
    try:
        data = response.json()
    except ValueError:
        raise AccessError("MCP OAuth 서버 응답을 확인할 수 없습니다.", "unavailable") from None
    if not isinstance(data, dict):
        raise AccessError("MCP OAuth 서버 응답을 확인할 수 없습니다.", "unavailable")
    return response.status_code, data


async def _discover(client, resource):
    # 서버의 401 challenge와 RFC 9728 well-known 경로를 순서대로 확인한다.
    public_url(resource)
    response = await client.get(resource, headers={"Accept": "application/json, text/event-stream"})
    challenge = _challenge(response.headers.get("www-authenticate", ""))
    candidates = []
    if challenge.get("resource_metadata"):
        candidates.append(public_url(challenge["resource_metadata"]))
    candidates.extend([_well_known(resource, "oauth-protected-resource"),
                       _base(resource) + "/.well-known/oauth-protected-resource"])
    metadata = None
    for url in dict.fromkeys(candidates):
        status, found = await _json_request(client, "GET", url)
        if status == 200:
            metadata = found
            break
        if status not in (404, 405):
            raise AccessError("MCP 리소스 인증 정보를 확인할 수 없습니다.", "unavailable")
    if not metadata or metadata.get("resource", "").rstrip("/") != resource.rstrip("/"):
        raise AccessError("MCP 리소스 인증 정보가 일치하지 않습니다.", "unavailable")
    servers = metadata.get("authorization_servers")
    if not isinstance(servers, list) or not servers or not isinstance(servers[0], str):
        raise AccessError("MCP 인증 서버를 확인할 수 없습니다.", "unavailable")
    issuer = public_url(servers[0]).rstrip("/")
    parsed = urlsplit(issuer)
    options = [_well_known(issuer, "oauth-authorization-server"),
               _well_known(issuer, "openid-configuration"),
               issuer + "/.well-known/openid-configuration"]
    authorization = None
    for url in dict.fromkeys(options):
        status, found = await _json_request(client, "GET", url)
        if status == 200:
            authorization = found
            break
        if status not in (404, 405):
            raise AccessError("MCP 인증 서버 정보를 확인할 수 없습니다.", "unavailable")
    if not authorization or authorization.get("issuer", "").rstrip("/") != issuer:
        raise AccessError("MCP 인증 서버의 발급자가 일치하지 않습니다.", "unavailable")
    for key in ("authorization_endpoint", "token_endpoint"):
        if not isinstance(authorization.get(key), str):
            raise AccessError("MCP 인증 서버 설정이 불완전합니다.", "unavailable")
        public_url(authorization[key])
    methods = authorization.get("code_challenge_methods_supported", [])
    if methods and "S256" not in methods:
        raise AccessError("MCP 인증 서버가 PKCE S256을 지원하지 않습니다.", "unavailable")
    return metadata, authorization, challenge


async def _select_client(client, row, saved, origin, authorization):
    if row.get("oauth_client_id"):
        secret = saved.get("oauth_client_secret")
        supported = authorization.get("token_endpoint_auth_methods_supported", ["client_secret_basic"])
        method = "none"
        if secret:
            if "client_secret_basic" in supported:
                method = "client_secret_basic"
            elif "client_secret_post" in supported:
                method = "client_secret_post"
            else:
                raise AccessError("지원하지 않는 MCP OAuth 클라이언트 인증입니다.", "unavailable")
        return {"client_id": row["oauth_client_id"], "client_secret": secret, "method": method}
    if authorization.get("client_id_metadata_document_supported") is True:
        return {"client_id": origin + "/oauth/mcp-client-metadata.json", "client_secret": None}
    registration = authorization.get("registration_endpoint")
    if not isinstance(registration, str):
        raise AccessError("이 MCP 서버에는 사전에 등록된 OAuth 클라이언트 정보가 필요합니다.", "unavailable")
    registration = public_url(registration)
    metadata = {"client_name": "MAGI", "redirect_uris": [origin + "/auth/mcp/callback"],
                "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
                "token_endpoint_auth_method": "none"}
    status, result = await _json_request(client, "POST", registration, json=metadata)
    if status not in (200, 201) or not result or not isinstance(result.get("client_id"), str) or not result["client_id"]:
        raise AccessError("MCP OAuth 클라이언트를 등록할 수 없습니다.", "unavailable")
    method = result.get("token_endpoint_auth_method", "none")
    if method not in {"none", "client_secret_basic", "client_secret_post"}:
        raise AccessError("지원하지 않는 MCP OAuth 클라이언트 인증입니다.", "unavailable")
    return {"client_id": result["client_id"], "client_secret": result.get("client_secret"), "method": method}


def _run(coro):
    try:
        return asyncio.run(asyncio.wait_for(coro, timeout=_REQUEST_TIMEOUT))
    except AccessError:
        raise
    except Exception:
        raise AccessError("MCP OAuth 연결을 완료하지 못했습니다.", "unavailable") from None


async def _prepare(row, saved, origin):
    async with public_client() as client:
        metadata, authorization, challenge = await _discover(client, row["url"])
        registered = await _select_client(client, row, saved, origin, authorization)
    # 브라우저로 전송할 인증 주소도 비공개 주소로 해석되는지 확인한다.
    authorize_url = urlsplit(authorization["authorization_endpoint"])
    host, port = authorize_url.hostname, authorize_url.port or 443
    try:
        answers = await anyio.getaddrinfo(host, port, type=1)
        if not answers or any(not is_public_ip(item[4][0]) for item in answers):
            raise ValueError()
    except (OSError, ValueError):
        raise AccessError("MCP 인증 서버 주소를 확인할 수 없습니다.", "unavailable") from None
    # 서버가 가능한 모든 권한을 광고해도 필요한 권한이라는 뜻은 아니다.
    scopes = challenge.get("scope") or ""
    if not isinstance(scopes, str) or len(scopes) > 2048 or any(ord(ch) < 32 for ch in scopes):
        raise AccessError("MCP OAuth 권한 범위를 확인할 수 없습니다.", "unavailable")
    return authorization, registered, scopes


def begin(store, owner_id, connection_id, sid, origin):
    if not isinstance(sid, str) or not sid or not isinstance(origin, str):
        raise AccessError("MCP OAuth 세션을 확인할 수 없습니다.", "unauthorized")
    public_url(origin)
    with store.transaction(mode="read") as conn:
        row = dict(_row(conn, owner_id, connection_id))
    saved = unseal(owner_id, connection_id, row["secret_ciphertext"])
    authorization, registered, scopes = _run(_prepare(row, saved, origin))
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode("ascii")
    payload = {"verifier": verifier, "origin": origin, "resource": row["url"],
               "issuer": authorization["issuer"], "token_endpoint": authorization["token_endpoint"],
               "client": registered, "version": row["version"] + 1}
    with store.transaction() as conn:
        current = _row(conn, owner_id, connection_id, lock=True)
        if current["version"] != row["version"]:
            raise AccessError("MCP 연결이 변경되어 다시 연결해야 합니다.", "busy")
        ciphertext = seal(owner_id, connection_id, payload)
        # 새 연결 시도는 이전 인증 결과가 나중에 도착해 덮어쓰는 것을 방지한다.
        conn.execute("UPDATE mcp_connections SET version=version+1,status='auth_required',enabled=false,updated_at=now() WHERE owner_id=%s AND id=%s",
                     (owner_id, connection_id))
        conn.execute("DELETE FROM mcp_oauth_states WHERE owner_id=%s AND connection_id=%s", (owner_id, connection_id))
        conn.execute("INSERT INTO mcp_oauth_states(state_hash,owner_id,connection_id,session_hash,expires_at,payload_ciphertext) VALUES (%s,%s,%s,%s,%s,%s)",
                     (_hash(state), owner_id, connection_id, _hash(sid), time.time() + _STATE_LIFETIME, ciphertext))
    params = {"response_type": "code", "client_id": registered["client_id"],
              "redirect_uri": origin + "/auth/mcp/callback", "state": state,
              "code_challenge": challenge, "code_challenge_method": "S256", "resource": row["url"]}
    if scopes:
        params["scope"] = scopes
    endpoint = authorization["authorization_endpoint"]
    parsed = urlsplit(endpoint)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if any(key in params for key, _ in query):
        raise AccessError("MCP 인증 서버 주소를 확인할 수 없습니다.", "unavailable")
    return {"url": urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query + list(params.items())), ""))}


async def _exchange(grant, fields):
    client_info = grant["client"]
    form = {**fields, "client_id": client_info["client_id"], "resource": grant["resource"]}
    secret = client_info.get("client_secret")
    method = client_info.get("method") or ("client_secret_basic" if secret else "none")
    auth = None
    if secret and method == "client_secret_basic":
        # RFC 6749: Basic 인증 전 각 항목을 form encoding한다.
        auth = (quote_plus(client_info["client_id"]), quote_plus(secret))
    elif secret and method == "client_secret_post":
        form["client_secret"] = secret
    elif secret or method != "none":
        raise AccessError("MCP OAuth 클라이언트 인증을 확인할 수 없습니다.", "unavailable")
    async with public_client() as client:
        status, result = await _json_request(client, "POST", grant["token_endpoint"], data=form, auth=auth)
    if status != 200 or not result:
        raise AccessError("MCP 인증을 완료하지 못했습니다. 다시 연결하세요.", "unavailable")
    access = result.get("access_token")
    expires = result.get("expires_in")
    refresh = result.get("refresh_token")
    if (not isinstance(access, str) or not access or len(access) > 16384 or
            result.get("token_type", "").lower() != "bearer" or
            (expires is not None and (type(expires) not in (int, float) or not 0 < expires <= 315360000)) or
            (refresh is not None and (not isinstance(refresh, str) or not refresh or len(refresh) > 16384))):
        raise AccessError("MCP 인증 응답을 확인할 수 없습니다.", "unavailable")
    return {"access_token": access, "refresh_token": refresh,
            "expires_at": time.time() + expires if expires is not None else None}


def callback(store, owner_id, sid, state, code, origin):
    if not all(isinstance(item, str) and item and len(item) <= 4096 for item in (sid, state, code, origin)):
        raise AccessError("MCP OAuth 응답을 확인할 수 없습니다.", "invalid")
    # 2026-11-03: 일회성 state를 네트워크 요청 전에 소비해 중복 코드 교환을 막는다.
    with store.transaction() as conn:
        row = conn.execute("DELETE FROM mcp_oauth_states WHERE state_hash=%s AND owner_id=%s AND session_hash=%s AND expires_at>%s RETURNING connection_id,payload_ciphertext",
                           (_hash(state), owner_id, _hash(sid), time.time())).fetchone()
    if not row:
        raise AccessError("MCP 인증 요청이 만료되었거나 일치하지 않습니다.", "invalid")
    ident = row["connection_id"]
    grant = unseal(owner_id, ident, row["payload_ciphertext"])
    if not hmac.compare_digest(grant["origin"], origin):
        raise AccessError("MCP 인증 출처가 일치하지 않습니다.", "invalid")
    with store.transaction(mode="read") as conn:
        current = _row(conn, owner_id, ident)
        if current["url"] != grant["resource"] or current["version"] != grant["version"]:
            raise AccessError("MCP 연결이 변경되어 다시 연결해야 합니다.", "invalid")
    tokens = _run(_exchange(grant, {"grant_type": "authorization_code", "code": code,
                                    "redirect_uri": origin + "/auth/mcp/callback", "code_verifier": grant["verifier"]}))
    with store.transaction() as conn:
        current = _row(conn, owner_id, ident, lock=True)
        if current["url"] != grant["resource"] or current["version"] != grant["version"]:
            raise AccessError("MCP 연결이 변경되어 다시 연결해야 합니다.", "invalid")
        saved = unseal(owner_id, ident, current["secret_ciphertext"])
        saved["oauth_grant"] = {key: grant[key] for key in ("resource", "issuer", "token_endpoint", "client")}
        saved["oauth_tokens"] = tokens
        conn.execute("UPDATE mcp_connections SET secret_ciphertext=%s,status='disconnected',enabled=false,updated_at=now() WHERE owner_id=%s AND id=%s",
                     (seal(owner_id, ident, saved), owner_id, ident))
        conn.execute("DELETE FROM mcp_oauth_refreshes WHERE owner_id=%s AND connection_id=%s", (owner_id, ident))


def _disable(store, owner_id, connection_id, version):
    with store.transaction() as conn:
        conn.execute("UPDATE mcp_connections SET status='auth_required',enabled=false,updated_at=now() WHERE owner_id=%s AND id=%s AND version=%s",
                     (owner_id, connection_id, version))


def token(store, owner_id, connection_id, *, expected_version, expected_resource):
    expired_without_refresh = False
    with store.transaction() as conn:
        row = _row(conn, owner_id, connection_id, lock=True)
        # 2026-11-04: 이전 URL의 요청이 새 연결의 토큰을 가져가지 않게 묶는다.
        if row["version"] != expected_version or row["url"] != expected_resource:
            raise AccessError("MCP 연결이 변경되어 다시 확인해야 합니다.", "invalid")
        saved = unseal(owner_id, connection_id, row["secret_ciphertext"])
        grant, tokens = saved.get("oauth_grant"), saved.get("oauth_tokens")
        if not isinstance(grant, dict) or not isinstance(tokens, dict) or grant.get("resource") != row["url"]:
            raise AccessError("MCP OAuth 연결을 다시 설정하세요.", "unavailable")
        if tokens.get("access_token") and (tokens.get("expires_at") is None or tokens["expires_at"] > time.time() + 30):
            return tokens["access_token"]
        if not tokens.get("refresh_token"):
            expired_without_refresh = True
        # 외부 호출 전 영속 예약한다. 프로세스 중단 후에도 동일 refresh token을 재전송하지 않는다.
        if not expired_without_refresh:
            reserved = conn.execute("INSERT INTO mcp_oauth_refreshes(connection_id,owner_id,started_at) VALUES (%s,%s,%s) ON CONFLICT(connection_id) DO NOTHING RETURNING connection_id",
                                    (connection_id, owner_id, time.time())).fetchone()
            if not reserved:
                raise AccessError("MCP OAuth 갱신이 진행 중이거나 완료 여부를 확인할 수 없습니다. 다시 연결하세요.", "busy")
        version = row["version"]
    if expired_without_refresh:
        _disable(store, owner_id, connection_id, version)
        raise AccessError("MCP OAuth 인증이 만료되었습니다. 다시 연결하세요.", "unavailable")
    try:
        fresh = _run(_exchange(grant, {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}))
        if fresh["refresh_token"] is None:
            fresh["refresh_token"] = tokens["refresh_token"]
        with store.transaction() as conn:
            current = _row(conn, owner_id, connection_id, lock=True)
            if current["version"] != version or current["url"] != grant["resource"]:
                raise AccessError("MCP 연결이 변경되어 다시 연결해야 합니다.", "invalid")
            current_saved = unseal(owner_id, connection_id, current["secret_ciphertext"])
            current_saved["oauth_tokens"] = fresh
            conn.execute("UPDATE mcp_connections SET secret_ciphertext=%s,updated_at=now() WHERE owner_id=%s AND id=%s",
                         (seal(owner_id, connection_id, current_saved), owner_id, connection_id))
            conn.execute("DELETE FROM mcp_oauth_refreshes WHERE owner_id=%s AND connection_id=%s", (owner_id, connection_id))
        return fresh["access_token"]
    except Exception:
        _disable(store, owner_id, connection_id, version)
        raise AccessError("MCP 인증 갱신을 완료하지 못했습니다. 다시 연결하세요.", "unavailable") from None
