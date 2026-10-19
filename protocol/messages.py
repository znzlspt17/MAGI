"""Shared JSON message validation for the MAGI loopback transport."""

from __future__ import annotations

import json
from decimal import Decimal


MAX_MESSAGE_BYTES = 128 * 1024
METHODS = {"list", "get", "generate", "answer", "revise", "approve", "download", "document", "subscribe"}
METHODS |= {"projects.list", "projects.create", "projects.assign", "knowledge.search",
            "knowledge.graph", "knowledge.node", "knowledge.document", "knowledge.retry"}
METHODS |= {"cleanup.catalog", "cleanup.preview", "cleanup.execute"}
METHODS.add("continue")
METHODS |= {'admin.projects','admin.graph','admin.search','admin.node','admin.document','admin.jobs'}
METHODS |= {'auth.info','auth.start','auth.callback','auth.me','auth.logout','service.status','usage',
            'lease.keep','lease.release','lease.resume','admin.overview','admin.user','admin.claim','admin.stop','admin.job','admin.settle','admin.settings'}


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
    if not isinstance(method, str) or method not in METHODS:
        return None
    if not isinstance(params, dict):
        return None
    result = {"request_id": request_id, "method": method, "params": params}
    for key in ('session','csrf','idempotency_key'):
        if key in data:
            if not isinstance(data[key],str) or len(data[key])>512:
                return None
            result[key]=data[key]
    return result


def result(request_id: str, value: object) -> str:
    def encode(item):
        if isinstance(item,Decimal):
            return str(item)
        raise TypeError('Unsupported protocol value')
    return json.dumps({"request_id": request_id, "result": value}, ensure_ascii=False, default=encode)


def error(request_id: str, message: str, code: str = "internal") -> str:
    return json.dumps(
        {"request_id": request_id, "error": {"code": code, "message": message}},
        ensure_ascii=False,
    )
