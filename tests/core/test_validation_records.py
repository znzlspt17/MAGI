"""과거 검증 문서의 안전한 해석과 관리자 전용 페이지 조회."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask
import pytest

from backend.access.context import AccessError
from backend.access.validation import DOCUMENT, safe_record, validation_page

JOB = "a" * 32
OTHER = "b" * 32
EXECUTION = "c" * 32
FOREIGN_EXECUTION = "d" * 32
ADMIN = {"role": "admin"}


def service(store):
    def require_admin(actor):
        if actor.get("role") != "admin":
            raise AccessError("관리자 권한이 필요합니다.")
    return SimpleNamespace(store=store, require_admin=require_admin)


@pytest.mark.parametrize("detail,reason,section,index", [
    ("out_of_scope: include at least one substantive content block.", "empty_section", "out_of_scope", None),
    ("background[2].item_id: use a unique nonempty stable ID without the LOCKED- prefix.", "invalid_item_id", "background", 2),
    ("architecture[0].text: include substantive English content.", "empty_text", "architecture", 0),
    ("architecture[1]: use only supplied requirement IDs and known decision IDs.", "unknown_reference", "architecture", 1),
    ("architecture[1].requirement_ids: use only supplied requirement IDs.", "unknown_requirement", "architecture", 1),
    ("architecture[1].decision_ids: use only known decision IDs.", "unknown_decision", "architecture", 1),
    ("background[0].text: omit fixed section headings and Locked Constraints headings; the application renders them.", "fixed_heading", "background", 0),
])
def test_legacy_only_accepts_whole_fixed_rules(detail, reason, section, index):
    value = safe_record(json.dumps({"stage": "spec_compile", "failed_checks": ["spec_blocks"], "attempt": 4, "validation_details": [detail]}))
    assert value["validation_reason"] == reason and value["validation_section"] == section and value["validation_index"] == index
    assert value["execution_link"] == "unconfirmed" and value["attempt"] == 4
    assert "validation_details" not in value


@pytest.mark.parametrize("payload", [
    {}, {"stage": "OTHER_PRIVATE"}, {"stage": "spec_compile", "validation_details": ["PRIVATE_INPUT"]},
    {"stage": "spec_compile", "failed_checks": ["spec_blocks"], "validation_details": ["PRIVATE[0].text: include substantive English content."]},
    {"stage": "spec_compile", "failed_checks": ["spec_blocks"], "validation_details": ["background[0].text: include substantive English content. PRIVATE"]},
    {"stage": "spec_compile", "failed_checks": ["spec_blocks"], "validation_reason": "PRIVATE", "validation_section": "PRIVATE", "validation_index": "PRIVATE", "execution_id": "PRIVATE"},
])
def test_unknown_data_is_not_reflected(payload):
    value = safe_record(json.dumps(payload))
    assert value["state"] == "unrecognized" and "PRIVATE" not in json.dumps(value)


@pytest.mark.parametrize("content", ["not-json", "[]", None, "x" * 65537], ids=["invalid", "array", "absent", "oversized"])
def test_corrupt_or_oversized_record_is_unreadable(content):
    assert safe_record(content)["state"] == "unreadable"


@pytest.mark.parametrize("params", [{"id": "bad"}, {"id": JOB, "path": ".env"}, {"id": JOB, "limit": 101}, {"id": JOB, "limit": 0}, {"id": JOB, "limit": True}, {"id": JOB, "offset": -1}])
def test_invalid_parameters_do_not_access_database(params):
    store = Mock()
    with pytest.raises(AccessError) as error: validation_page(service(store), ADMIN, params)
    assert error.value.code == "invalid"
    store.transaction.assert_not_called()


def test_versions_are_isolated_paginated_and_execution_links_are_verified(store):
    project = store.create_project("진단 테스트")
    for ident in (JOB, OTHER): store.save_job({"id": ident, "project_id": project["id"]})
    with store.transaction() as conn:
        for execution, ident in ((EXECUTION, JOB), (FOREIGN_EXECUTION, OTHER)):
            conn.execute("INSERT INTO executions(id,job_id,data) VALUES (%s,%s,'{}')", (execution, ident))
    docs = store.documents(JOB)
    legacy = {"stage": "spec_compile", "failed_checks": ["spec_blocks"], "attempt": 4,
              "validation_details": ["out_of_scope: include at least one substantive content block."]}
    docs.write_json(DOCUMENT, legacy)
    new = {**legacy, "execution_id": EXECUTION, "validation_reason": "unknown_requirement", "validation_section": "architecture", "validation_index": 2, "validation_field": "requirement_ids", "validation_details": ["PRIVATE_RESPONSE"]}
    docs.write_json(DOCUMENT, new)
    docs.write_json(DOCUMENT, {**new, "execution_id": FOREIGN_EXECUTION})
    docs.write_text(DOCUMENT, "PRIVATE_INVALID_JSON")
    store.documents(OTHER).write_json(DOCUMENT, {**legacy, "execution_id": FOREIGN_EXECUTION})
    store.documents(JOB).write_json("analysis/unrelated.json", {"PRIVATE": "must not read"})
    from backend.access.service import PublicService
    first = PublicService.admin(service(store), ADMIN, "admin.job.validation", {"id": JOB, "limit": 2})
    assert first["next_offset"] == 2 and len(first["items"]) == 2
    assert first["items"][0]["state"] == "unreadable"
    assert first["items"][1]["execution_id"] is None
    second = validation_page(service(store), ADMIN, {"id": JOB, "limit": 2, "offset": 2})
    assert second["next_offset"] is None
    assert second["items"][0]["execution_id"] == EXECUTION and second["items"][0]["execution_link"] == "confirmed"
    assert second["items"][0]["validation_field"] == "requirement_ids"
    assert second["items"][1]["execution_link"] == "unconfirmed"
    assert all(item["created_at"].endswith("+09:00") for item in second["items"])
    assert "PRIVATE" not in json.dumps(first) + json.dumps(second)
    assert not ({item["record_id"] for item in first["items"]} & {item["record_id"] for item in second["items"]})
    docs.write_text(DOCUMENT, "x" * 65537)
    assert validation_page(service(store), ADMIN, {"id": JOB})["items"][0]["state"] == "unreadable"
    with pytest.raises(AccessError): validation_page(service(store), {"role": "user"}, {"id": JOB})
    with pytest.raises(AccessError) as error: validation_page(service(store), ADMIN, {"id": "f" * 32})
    assert error.value.code == "not_found"


@pytest.mark.parametrize("role,status", [("admin", 200), ("user", 403), (None, 401)])
def test_gateway_authorization_and_rpc_registration(role, status):
    from gateway.public import install
    from gateway.client import ClientError
    from protocol.messages import parse_request
    app = Flask(__name__)
    app.config.update(PUBLIC_MODE=True, PUBLIC_ORIGIN="https://magi.test", LOCAL_LOGIN=False, PROXY_HOPS=0)
    calls = []
    class Client:
        def call(self, method, params=None):
            if method == "auth.me":
                if role is None: raise ClientError("로그인이 필요합니다.", status=401)
                return {"role": role}
            calls.append((method, params)); return {"items": []}
    install(app, lambda: Client())
    response = app.test_client().get("/api/admin/job/validation?id=" + JOB, base_url="https://magi.test")
    assert response.status_code == status and bool(calls) == (role == "admin")
    if role == "admin":
        assert calls == [("admin.job.validation", {"id": JOB})]
        assert response.headers["Cache-Control"] == "no-store"
        duplicate = app.test_client().get("/api/admin/job/validation?id=x&id=y", base_url="https://magi.test")
        assert duplicate.status_code == 400 and len(calls) == 1
    assert parse_request(json.dumps({"request_id": "test", "method": "admin.job.validation", "params": {"id": JOB}}))


@pytest.mark.parametrize("field,expected", [("item_id", "item_id"), ("PRIVATE_FIELD", None), (["text"], None)])
def test_new_field_is_allowlisted(field, expected):
    record = safe_record(json.dumps({"stage": "spec_compile", "failed_checks": ["spec_blocks"],
        "validation_reason": "duplicate_item_id", "validation_section": "background",
        "validation_index": 0, "validation_field": field, "validation_details": ["PRIVATE_RESPONSE"]}))
    assert record["state"] == "recognized"
    assert record["validation_field"] == expected
    assert "PRIVATE" not in json.dumps(record)
