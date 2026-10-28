"""관리자가 저장된 명세 검증 기록을 원문 노출 없이 조회하는 경계."""

from datetime import datetime
import json
import re

from backend.access.context import AccessError
from backend.errors import SpecCompilationError
from backend.models import SpecResponse
from protocol.logging import KST

DOCUMENT = "analysis/spec_compile_validation.json"
_ID = re.compile(r"[0-9a-f]{32}\Z")
_SECTIONS = set(SpecResponse.model_fields) - {"decisions", "spec_links"}
_REASONS = SpecCompilationError.block_reasons | {"unknown_reference"}
_LEGACY_RULES = {
    ("", "include at least one substantive content block."): "empty_section",
    (".item_id", "use a unique nonempty stable ID without the LOCKED- prefix."): "invalid_item_id",
    (".text", "include substantive English content."): "empty_text",
    ("", "use only supplied requirement IDs and known decision IDs."): "unknown_reference",
    (".requirement_ids", "use only supplied requirement IDs."): "unknown_requirement",
    (".decision_ids", "use only known decision IDs."): "unknown_decision",
    (".text", "omit fixed section headings and Locked Constraints headings; the application renders them."): "fixed_heading",
}


def _integer(value, default, maximum):
    if value is None:
        return default
    if type(value) is not int and (not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,6}", value)):
        raise AccessError("조회 개수를 확인하세요.", "invalid")
    value = int(value)
    if not 0 <= value <= maximum:
        raise AccessError("조회 개수를 확인하세요.", "invalid")
    return value


def _legacy(details):
    # 고정된 서버 문구 전체와 일치하는 경우만 해석한다. 임의 문장의 일부는 사용하지 않는다.
    if not isinstance(details, list) or len(details) != 1 or not isinstance(details[0], str) or len(details[0]) > 600:
        return None
    match = re.fullmatch(r"([a-z_]+)(?:\[([0-9]{1,6})\])?(\.[a-z_]+)?: (.+)", details[0])
    if not match or match[1] not in _SECTIONS:
        return None
    reason = _LEGACY_RULES.get((match[3] or "", match[4]))
    index = int(match[2]) if match[2] is not None else None
    if reason is None or (reason == "empty_section") != (index is None) or (index is not None and index > 100000):
        return None
    return reason, match[1], index


def safe_record(content):
    """파싱 결과에도 문서 원문이나 임의 문자열을 포함하지 않는다."""
    result = {"state": "unrecognized", "stage": "spec_compile", "error_code": None,
              "failed_checks": [], "attempt": None, "execution_id": None,
              "execution_link": "unconfirmed", "validation_reason": None,
              "validation_section": None, "validation_index": None, "validation_field": None}
    try:
        value = json.loads(content) if isinstance(content, str) and len(content) <= 65536 else None
    except (ValueError, RecursionError):
        value = None
    if not isinstance(value, dict):
        return {**result, "state": "unreadable"}
    if value.get("stage") != "spec_compile":
        return result
    if isinstance(value.get("failed_checks"), list):
        result["failed_checks"] = sorted({check for check in value["failed_checks"] if isinstance(check, str) and check in SpecCompilationError.checks})
    if result["failed_checks"]:
        result["error_code"] = SpecCompilationError.code
    if type(value.get("attempt")) is int and 1 <= value["attempt"] <= 4:
        result["attempt"] = value["attempt"]
    reason = value.get("validation_reason", value.get("block_reason"))
    section = value.get("validation_section", value.get("block_section"))
    index = value.get("validation_index", value.get("block_index"))
    valid_index = index is None if reason == "empty_section" else type(index) is int and 0 <= index <= 100000
    if ("spec_blocks" in result["failed_checks"] and isinstance(reason, str) and reason in _REASONS
            and isinstance(section, str) and section in _SECTIONS and valid_index):
        parsed = reason, section, index
    else:
        parsed = _legacy(value.get("validation_details")) if "spec_blocks" in result["failed_checks"] else None
    if parsed:
        result.update(state="recognized", validation_reason=parsed[0], validation_section=parsed[1], validation_index=parsed[2])
    field = value.get("validation_field")
    if parsed and isinstance(field, str) and field in SpecCompilationError.block_fields:
        result["validation_field"] = field
    execution = value.get("execution_id")
    if isinstance(execution, str) and _ID.fullmatch(execution):
        result["execution_id"] = execution
    return result


def _time(value):
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
        return date.astimezone(KST).isoformat() if isinstance(date, datetime) and date.tzinfo else None
    except (ValueError, OverflowError):
        return None


def validation_page(service, actor, params):
    service.require_admin(actor)
    if not isinstance(params, dict) or set(params) - {"id", "limit", "offset"}:
        raise AccessError("지원하지 않는 진단 조회 조건입니다.", "invalid")
    ident = params.get("id")
    if not isinstance(ident, str) or not _ID.fullmatch(ident):
        raise AccessError("작업 ID를 확인하세요.", "invalid")
    limit, offset = _integer(params.get("limit"), 20, 100), _integer(params.get("offset"), 0, 100000)
    if not limit:
        raise AccessError("조회 개수를 확인하세요.", "invalid")
    with service.store.transaction(mode="read") as conn:
        if not conn.execute("SELECT id FROM jobs WHERE id=%s", (ident,)).fetchone():
            raise AccessError("작업을 찾을 수 없습니다.", "not_found")
        rows = conn.execute(
            "SELECT d.id,d.created_at,CASE WHEN octet_length(b.content)<=65536 THEN b.content ELSE NULL END AS content "
            "FROM document_versions d JOIN document_bodies b ON (b.job_id,b.hash)=(d.job_id,d.content_hash) "
            "WHERE d.job_id=%s AND d.name=%s ORDER BY d.sequence DESC LIMIT %s OFFSET %s",
            (ident, DOCUMENT, limit + 1, offset),
        ).fetchall()
        items = [{"record_id": row["id"], "created_at": _time(row["created_at"]), **safe_record(row["content"])} for row in rows[:limit]]
        candidates = list({item["execution_id"] for item in items if item["execution_id"]})
        linked = {row["id"] for row in conn.execute("SELECT id FROM executions WHERE job_id=%s AND id=ANY(%s)", (ident, candidates)).fetchall()} if candidates else set()
        for item in items:
            if item["execution_id"] in linked:
                item["execution_link"] = "confirmed"
            else:
                item["execution_id"] = None
    return {"items": items, "limit": limit, "offset": offset,
            "next_offset": offset + limit if len(rows) > limit and offset + limit <= 100000 else None}
