"""외부 MCP 통신과 스키마의 신뢰 경계."""

from __future__ import annotations

import ipaddress
import json
from urllib.parse import urlsplit

import anyio
import httpcore
import httpx
from httpcore._backends.auto import AutoBackend
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError


class MCPValidationError(ValueError):
    pass


_TRANSITION_PREFIXES = tuple(ipaddress.ip_network(value) for value in (
    "64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32"))


def is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if not ip.is_global or ip.is_multicast:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped or any(ip in prefix for prefix in _TRANSITION_PREFIXES):
            return False
    return True


def public_url(value: str) -> str:
    """2026-11-03: 사용자 URL을 내부 주소와 인증정보가 없는 HTTPS로 제한한다."""
    if not isinstance(value, str) or len(value) > 2048:
        raise MCPValidationError("서버 주소를 확인하세요.")
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.username is not None
                or url.password is not None or url.fragment or (url.port is not None and not 1 <= url.port <= 65535)):
            raise ValueError()
        host = url.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
            raise ValueError()
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if ip is not None and not is_public_ip(host):
            raise ValueError()
    except (ValueError, TypeError):
        raise MCPValidationError("공개 HTTPS 서버 주소가 필요합니다.") from None
    return value


class PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    """DNS 결과를 검증한 IP로 직접 연결해 검증과 연결 사이 재해석을 막는다."""

    def __init__(self, backend=None):
        self.backend = backend or AutoBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        public_url(f"https://[{host}]:{port}/" if ":" in host else f"https://{host}:{port}/")
        try:
            resolved = await anyio.getaddrinfo(host, port, type=1)
            addresses = list(dict.fromkeys(entry[4][0] for entry in resolved))
            if not addresses or any(not is_public_ip(addr) for addr in addresses):
                raise MCPValidationError("공개 네트워크 주소가 필요합니다.")
        except MCPValidationError:
            raise
        except (OSError, ValueError):
            raise MCPValidationError("서버 주소를 확인할 수 없습니다.") from None
        # TLS SNI와 인증서 검증은 httpcore가 원래 호스트 이름으로 수행한다.
        return await self.backend.connect_tcp(addresses[0], port, timeout=timeout,
            local_address=local_address, socket_options=socket_options)

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise MCPValidationError("지원하지 않는 연결 방식입니다.")

    async def sleep(self, seconds):
        await self.backend.sleep(seconds)


class PublicTransport(httpx.AsyncHTTPTransport):
    def __init__(self):
        super().__init__(trust_env=False, retries=0)
        self._pool._network_backend = PublicNetworkBackend()

    async def handle_async_request(self, request):
        public_url(str(request.url))
        request.headers["Accept-Encoding"] = "identity"
        response = await super().handle_async_request(request)
        if 300 <= response.status_code < 400:
            await response.aclose()
            raise MCPValidationError("서버 리다이렉트는 지원하지 않습니다.")
        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
            await response.aclose()
            raise MCPValidationError("압축된 서버 응답은 지원하지 않습니다.")
        response.stream = BoundedStream(response.stream)
        return response


class BoundedStream(httpx.AsyncByteStream):
    """서버가 JSON 또는 SSE를 무제한 스트리밍하지 못하도록 제한한다."""

    def __init__(self, stream, limit=1024 * 1024):
        self.stream, self.limit = stream, limit

    async def __aiter__(self):
        count = 0
        async for part in self.stream:
            count += len(part)
            if count > self.limit:
                raise MCPValidationError("서버 응답이 너무 큽니다.")
            yield part

    async def aclose(self):
        await self.stream.aclose()


def public_client(*, headers=None):
    return httpx.AsyncClient(transport=PublicTransport(), headers=headers, timeout=30,
                             follow_redirects=False, trust_env=False)


def validate_schema(schema: dict) -> None:
    """외부 참조·과대 스키마를 차단하고 검증기 동작을 고정한다."""
    if not isinstance(schema, dict):
        raise MCPValidationError("도구 입력 스키마가 올바르지 않습니다.")
    try:
        if len(json.dumps(schema, ensure_ascii=False).encode("utf-8")) > 32768:
            raise MCPValidationError("도구 입력 스키마가 너무 큽니다.")
        dialect = schema.get("$schema")
        if dialect and dialect.rstrip("#/") != "https://json-schema.org/draft/2020-12/schema":
            raise MCPValidationError("지원하지 않는 스키마 버전입니다.")

        def visit(value, depth=0):
            if depth > 32:
                raise MCPValidationError("도구 입력 스키마가 너무 깊습니다.")
            if isinstance(value, dict):
                for key, child in value.items():
                    # 2026-11-03: 정규식 검증의 무한 CPU 점유를 샌드박스 없이 허용하지 않는다.
                    if key in {"pattern", "patternProperties"}:
                        raise MCPValidationError("정규식 입력 스키마는 지원하지 않습니다.")
                    if key in {"$ref", "$dynamicRef", "$recursiveRef"}:
                        raise MCPValidationError("스키마 참조는 지원하지 않습니다.")
                    visit(child, depth + 1)
            elif isinstance(value, list):
                for child in value:
                    visit(child, depth + 1)

        visit(schema)
        Draft202012Validator.check_schema(schema)
    except (SchemaError, TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, MCPValidationError):
            raise
        raise MCPValidationError("도구 입력 스키마가 올바르지 않습니다.") from None


def validate_arguments(schema: dict, arguments: object) -> dict:
    validate_schema(schema)
    if not isinstance(arguments, dict):
        raise MCPValidationError("도구 입력은 객체여야 합니다.")
    if len(json.dumps(arguments, ensure_ascii=False).encode("utf-8")) > 16384:
        raise MCPValidationError("도구 입력이 너무 큽니다.")
    try:
        Draft202012Validator(schema).validate(arguments)
    except (ValidationError, SchemaError, RecursionError):
        raise MCPValidationError("도구 입력이 스키마와 일치하지 않습니다.") from None
    except Exception:
        # 존재하지 않는 내부 참조도 검증 실패로만 취급한다.
        raise MCPValidationError("도구 입력 스키마를 검증할 수 없습니다.") from None
    return arguments
