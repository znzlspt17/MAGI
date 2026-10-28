"""관리자 필터만 허용하는 제한된 VictoriaLogs 조회 클라이언트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import http.client
import json
import re
import socket
import time
from urllib.parse import urlencode, urlsplit

from protocol.logging import KST, redact

SERVICES = {"backend", "gateway", "caddy", "postgresql"}
LEVELS = {"debug", "info", "warning", "error", "critical", "unknown"}
MAX_BYTES = 4 * 1024 * 1024


class LogError(Exception):
    def __init__(self, code, message, status=503):
        super().__init__(message)
        self.code, self.status = code, status


def _date(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(UTC)
    except (ValueError, AttributeError):
        raise LogError("invalid", "시간 범위를 확인하세요.", 400) from None


def filters(args, now=None):
    now = now or datetime.now(UTC)
    allowed = {"service", "level", "start", "end", "q", "trace_id", "job_id", "execution_id", "limit", "offset"}
    if set(args) - allowed or (hasattr(args, "getlist") and any(len(args.getlist(k)) != 1 for k in args)):
        raise LogError("invalid", "지원하지 않는 조회 조건입니다.", 400)
    end = _date(args["end"]) if args.get("end") else now
    start = _date(args["start"]) if args.get("start") else end - timedelta(minutes=15)
    # 과거 페이지의 고정 start가 보관 경계보다 조금 오래되어도 조회를 유지한다.
    if not now - timedelta(days=7) < end <= now + timedelta(seconds=5) or not start < end or end-start > timedelta(days=7):
        raise LogError("invalid", "최근 7일 이내의 시간 범위를 선택하세요.", 400)
    try:
        limit, offset = int(args.get("limit", 200)), int(args.get("offset", 0))
    except (ValueError, TypeError):
        raise LogError("invalid", "조회 개수를 확인하세요.", 400) from None
    if not 1 <= limit <= 500 or not 0 <= offset <= 10000 or offset and not args.get("end"):
        raise LogError("invalid", "조회 개수 또는 기준 시각을 확인하세요.", 400)
    clauses = ['service:in("backend","gateway","caddy","postgresql")']
    for field, choices in (("service", SERVICES), ("level", LEVELS)):
        value = args.get(field)
        if value:
            if value not in choices:
                raise LogError("invalid", "서비스 또는 로그 레벨을 확인하세요.", 400)
            clauses.append(f"{field}:={json.dumps(value)}")
    for field in ("trace_id", "job_id", "execution_id"):
        value = args.get(field)
        if value:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
                raise LogError("invalid", "식별값을 확인하세요.", 400)
            clauses.append(f"{field}:={json.dumps(value)}")
    if args.get("q"):
        value = args["q"]
        if len(value) > 256 or any(ord(c) < 32 for c in value):
            raise LogError("invalid", "검색어는 제어 문자 없이 256자까지 입력하세요.", 400)
        clauses.append(f"_msg:*{json.dumps(value, ensure_ascii=False)}*")
    return " AND ".join(clauses), start.isoformat(), end.isoformat(), limit, offset


class LogStore:
    def __init__(self, url):
        self.url = url

    def _fetch(self, path, data=None, timeout=5):
        if not self.url:
            raise LogError("not_configured", "로그 저장소가 설정되지 않았습니다.")
        try:
            target = urlsplit(self.url)
            port = target.port or 80
        except ValueError:
            raise LogError("not_configured", "로그 저장소 내부 주소 설정을 확인하세요.") from None
        if target.scheme != "http" or not target.hostname or target.username or target.password or target.path not in ("", "/") or target.query or target.fragment:
            raise LogError("not_configured", "로그 저장소 내부 주소 설정을 확인하세요.")
        connection = http.client.HTTPConnection(target.hostname, port, timeout=timeout)
        deadline = time.monotonic() + timeout
        try:
            body = urlencode(data) if data is not None else None
            connection.request("POST" if data is not None else "GET", path, body,
                               {"Content-Type": "application/x-www-form-urlencoded"} if body else {})
            transport = connection.sock
            if transport:
                transport.settimeout(max(.001, deadline - time.monotonic()))
            response = connection.getresponse()
            if response.status != 200:
                raise LogError("unavailable", "로그 저장소가 조회를 완료하지 못했습니다.")
            parts, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                if transport:
                    transport.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    raise LogError("too_large", "로그 응답이 큽니다. 기간이나 조회 개수를 줄이세요.")
                parts.append(chunk)
            return b"".join(parts).decode("utf-8")
        except (TimeoutError, socket.timeout):
            raise LogError("timeout", "로그 조회 시간이 초과되었습니다. 기간을 줄여주세요.", 504) from None
        except (OSError, http.client.HTTPException, UnicodeError, ValueError):
            raise LogError("unavailable", "로그 저장소에 연결할 수 없습니다.") from None
        finally:
            connection.close()

    def search(self, args):
        query, start, end, limit, offset = filters(args)
        raw = self._fetch("/select/logsql/query", {
            "query": query, "start": start, "end": end,
            "limit": limit + 1, "offset": offset, "timeout": "5s",
        })
        try:
            rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
            if any(not isinstance(row, dict) for row in rows):
                raise ValueError
            items = [normalize(row) for row in rows[:limit]]
        except (ValueError, TypeError):
            raise LogError("unavailable", "로그 저장소 응답을 확인할 수 없습니다.") from None
        items.sort(key=lambda row: row["timestamp"], reverse=True)
        return {"items": items, "start": start, "end": end, "next_offset": offset + limit if len(rows) > limit and offset + limit <= 10000 else None,
                "storage": {"state": "ready", "retention_days": 7}}

    def status(self):
        # 저장소 내부 메트릭 원문을 브라우저에 노출하지 않는다.
        metrics = self._fetch("/metrics", timeout=2)
        values = {}
        for line in metrics.splitlines():
            match = re.fullmatch(r'(vl_free_disk_space_bytes|vl_total_disk_space_bytes|vl_storage_is_read_only)(?:\{[^}]*\})? ([0-9.eE+\-]+)', line)
            if match:
                values[match[1]] = float(match[2])
        heartbeat = self._fetch("/select/logsql/query", {"query": 'service:="collector"', "start": "2m", "limit": 1, "timeout": "2s"}, timeout=2)
        warnings = []
        if not heartbeat.strip():
            warnings.append("최근 2분간 수집기 신호가 없습니다. 수집 상태를 확인하세요.")
        if values.get("vl_storage_is_read_only", 0):
            warnings.append("로그 저장소가 읽기 전용 상태입니다.")
        free = values.get("vl_free_disk_space_bytes")
        total = values.get("vl_total_disk_space_bytes")
        if free is not None and total is not None and total > 0 and free / total < 0.2:
            warnings.append("로그 저장 디스크 여유가 부족합니다. 호스트 여유 공간을 확인하세요.")
        if free is None:
            warnings.append("저장소 디스크 여유 지표를 확인할 수 없습니다.")
        return {"state": "ready", "warnings": warnings, "free_bytes": free,
                "retention_days": 7, "collector_seen": bool(heartbeat.strip())}


def _kst_timestamp(value):
    """저장소의 나노초 소수부를 보존하면서 KST ISO 시각으로 변환한다."""
    value = str(value)[:64]
    match = re.search(r"(\.\d+)?(?:Z|[+-]\d{2}:\d{2})$", value)
    if not match:
        return ""
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(KST)
    except ValueError:
        return ""
    return date.strftime("%Y-%m-%dT%H:%M:%S") + (match.group(1) or "") + "+09:00"


def normalize(row):
    fields = ("trace_id", "request_id", "job_id", "execution_id", "stage", "duration_ms", "error_code", "error_stage", "exception_type", "frames", "failed_checks", "attempt", "max_attempts", "method", "status", "container_name", "validation_reason", "validation_section", "validation_index", "validation_field")
    return {"timestamp": _kst_timestamp(row.get("_time", "")),
            "service": row.get("service") if row.get("service") in SERVICES else "unknown",
            "level": row.get("level") if row.get("level") in LEVELS else "unknown",
            "message": redact(str(row.get("_msg", ""))),
            "event": redact(str(row.get("event", "log")))[:128],
            "fields": {key: redact(str(row[key])) for key in fields if key in row}}
