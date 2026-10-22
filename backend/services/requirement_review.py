"""불변 명세에 기록된 요구사항 연결을 조회한다. 의미 판정과 테스트 실행은 하지 않는다."""

import re

from backend.errors import ArtifactError
from backend.knowledge.trace import REQUIREMENT_GROUPS
from backend.services.change_review import digest, normalize, document_blocks
from backend.services.spec_compiler import REQUIRED_FINAL_SPEC_HEADINGS
from backend.models import SpecResponse


VERIFICATION = {"acceptance_criteria", "test_plan", "manual_verification_checklist"}
SECTIONS = dict(zip(
    [h for h in REQUIRED_FINAL_SPEC_HEADINGS if h not in {"# Final Agent Specification", "## 4. Scope", "## 7. Mandatory Requirements"}],
    [f for f in SpecResponse.model_fields if f not in {"decisions", "spec_links"}],
))


def load_snapshot(writer, ident, content):
    if not isinstance(ident, str) or not re.fullmatch(r"[0-9a-f]{64}", ident):
        return None
    path = f"candidate_snapshots/{ident}.json"
    try:
        if not writer.path(path).is_file():
            return None
        packet = writer.read_json(path)
    except (OSError, ValueError, UnicodeError, ArtifactError):
        return None
    if not isinstance(packet, dict):
        return None
    if (packet.get("id") != ident or digest({k: v for k, v in packet.items() if k != "id"}) != ident
            or packet.get("content") != normalize(content)):
        return None
    return packet


def build_review(content, snapshot=None, *, basis_id=None, review_status="unknown", offset=0, query="", missing=False, evidence_for=None):
    if type(offset) is not int or offset < 0 or offset % 20 or not isinstance(query, str) or len(query) > 200:
        raise ValueError("근거표 조회 조건이 올바르지 않습니다.")
    text = normalize(content)
    snapshot = snapshot or {}
    sheet = snapshot.get("requirements", {})
    requirements = [{**item, "group": group} for group in REQUIREMENT_GROUPS for item in sheet.get(group, [])]
    known = {item["id"] for item in requirements}
    supplied = snapshot.get("compiled_blocks", [])
    # 구간을 원문에서 다시 확인한다. 모호한 중복 인용은 자동 연결하지 않는다.
    blocks = document_blocks(text, supplied)
    evidence, unlinked = [], []
    for block in blocks:
        section = SECTIONS.get(block["section"], "")
        refs = list(dict.fromkeys(ref for ref in block["requirement_ids"] if ref in known))
        item = {"item_id": block["item_id"], "section": section or block["section"],
                "quote": block["text"], "start": block["start"], "end": block["end"], "line": block["line"],
                "requirement_ids": refs, "shared": len(refs) > 1, "provenance": "recorded_block" if refs else "section_only"}
        # 제목과 공백만 있는 영역은 근거로 집계하지 않는다.
        if not re.sub(r"(?m)^#{1,3} .*$", "", item["quote"]).strip():
            continue
        evidence.append(item)
        if not refs and section in VERIFICATION:
            unlinked.append(item)
    rows = []
    for req in requirements:
        linked = [e for e in evidence if req["id"] in e["requirement_ids"]]
        concrete = [e for e in linked if e["section"] not in VERIFICATION | {"out_of_scope", "in_scope", "recommended_requirements", "optional_requirements"}
                    and not e["item_id"].startswith("LOCKED-")
                    and e["quote"].strip().removeprefix("- ").strip() not in {req["text"], f'[{req["id"]}] {req["text"]}'}]
        acceptance = [e for e in linked if e["section"] == "acceptance_criteria"]
        methods = [e for e in linked if e["section"] in {"test_plan", "manual_verification_checklist"}]
        rows.append({"id": req["id"], "text": req.get("original_text") or req["text"], "group": req["group"],
                     "specification": concrete, "acceptance": acceptance, "verification": methods,
                     "spec_status": "linked" if concrete else "unconfirmed", "acceptance_status": "linked" if acceptance else "unconfirmed",
                     "verification_status": "linked" if methods else "unconfirmed", "test_status": "not_collected"})
    applicable = [r for r in rows if r["group"] != "non_scope"]
    summary = {"total": len(applicable), "spec_linked": sum(r["spec_status"] == "linked" for r in applicable),
               "acceptance_linked": sum(r["acceptance_status"] == "linked" for r in applicable),
               "verification_linked": sum(r["verification_status"] == "linked" for r in applicable), "test_status": "not_collected"}
    selected = [r for r in rows if (not query or query.casefold() in (r["id"] + " " + r["text"]).casefold())
                and (not missing or any(r[k] != "linked" for k in ("spec_status", "acceptance_status", "verification_status")))]
    from backend.services.spec_translation import source_key

    def preview(ref, length):
        return {**ref, "quote": ref["quote"][:length], "end": ref["start"] + len(ref["quote"][:length]),
                "truncated": len(ref["quote"]) > length}

    result = {"basis": {"id": basis_id or digest(text), "source_hash": source_key(content)}, "status": "ready" if supplied and requirements else "limited",
            "review_status": review_status, "summary": summary, "rows": selected[offset:offset + 20],
            "unlinked": [preview(e, 140) for e in unlinked[offset:offset + 20]], "unlinked_total": len(unlinked),
            "total": len(selected), "offset": offset, "next_offset": offset + 20,
            "has_more": offset + 20 < len(selected),
            "message": "기록된 연결은 내용의 충분성이나 구현의 동작을 보증하지 않습니다. 실제 테스트 결과는 수집하지 않습니다."}
    if evidence_for is not None:
        if evidence_for == "__unlinked__":
            details = unlinked
        elif isinstance(evidence_for, str) and evidence_for in known:
            row = next(r for r in rows if r["id"] == evidence_for)
            details = [dict(e, category=category) for category in ("specification", "acceptance", "verification") for e in row[category]]
        else:
            raise ValueError("요구사항 근거를 확인할 수 없습니다.")
        result.update(rows=[], unlinked=[], evidence=[preview(e, 512) for e in details[offset:offset + 20]],
                      total=len(details), has_more=offset + 20 < len(details))
    else:
        # 표에서는 짧은 미리보기만 전송하고 전체 연결은 별도 페이지로 빠짐없이 조회한다.
        result["rows"] = [{**r, "text": r["text"][:240], "truncated": len(r["text"]) > 240,
                           **{k + "_total": len(r[k]) for k in ("specification", "acceptance", "verification")},
                           **{k: [preview(e, 140) for e in r[k][:1]] for k in ("specification", "acceptance", "verification")}}
                          for r in result["rows"]]
    return result
