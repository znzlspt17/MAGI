"""Shared JSON message validation for the MAGI loopback transport."""

from __future__ import annotations

import json
from decimal import Decimal


MAX_MESSAGE_BYTES = 128 * 1024
# None 항목은 인증 서비스 또는 구독·상태 경계에서 처리한다.
RPC_METHODS = {
    "list": "_list_jobs",
    "get": "_get_job",
    "document": "_document",
    "download": "_download",
    "requirement.review": "_requirement_review",
    "implementation.package": "_implementation_package",
    "implementation.package.file": "_implementation_package",
    "knowledge.impact": "_impact",
    "knowledge.impact.analyse": "_impact_analyse",
    "projects.list": "_knowledge",
    "projects.create": "_knowledge",
    "projects.decisions": "_knowledge",
    "projects.decisions.register": "_knowledge",
    "projects.decisions.deactivate": "_knowledge",
    "projects.decision_candidates": "_knowledge",
    "projects.reused_decisions": "_knowledge",
    "knowledge.search": "_knowledge",
    "knowledge.graph": "_knowledge",
    "knowledge.node": "_knowledge",
    "knowledge.document": "_knowledge",
    "job.command": None,
    "health.check": None,
    "subscribe": None,
    "knowledge.retry": None,
    "cleanup.catalog": None,
    "cleanup.preview": None,
    "cleanup.execute": None,
    "admin.projects": None,
    "admin.graph": None,
    "admin.search": None,
    "admin.node": None,
    "admin.document": None,
    "admin.jobs": None,
    "admin.usage": None,
    "admin.usage.rows": None,
    "auth.info": None,
    "auth.start": None,
    "auth.callback": None,
    "auth.me": None,
    "auth.logout": None,
    "service.status": None,
    "usage": None,
    "admin.overview": None,
    "admin.user": None,
    "admin.stop": None,
    "admin.job": None,
    "admin.settle": None,
    "admin.settings": None,
}


def parse_request(raw: object) -> dict | None:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    request_id = data.get("request_id")
    method = data.get("method")
    params = data.get("params")
    if not isinstance(request_id, str) or not request_id or len(request_id) > 64:
        return None
    if not isinstance(method, str) or method not in RPC_METHODS:
        return None
    if not isinstance(params, dict):
        return None
    result = {"request_id": request_id, "method": method, "params": params}
    for key in ("session", "csrf", "idempotency_key"):
        if key in data:
            if not isinstance(data[key], str) or len(data[key]) > 512:
                return None
            result[key] = data[key]
    return result


def result(request_id: str, value: object) -> str:
    def encode(item):
        if isinstance(item, Decimal):
            return str(item)
        raise TypeError("Unsupported protocol value")

    return json.dumps(
        {"request_id": request_id, "result": value}, ensure_ascii=False, default=encode
    )


def error(request_id: str, message: str, code: str = "internal") -> str:
    return json.dumps(
        {"request_id": request_id, "error": {"code": code, "message": message}},
        ensure_ascii=False,
    )
