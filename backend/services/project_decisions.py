"""승인된 구조화 결정의 공개 근거와 접수 당시 사본을 구성한다."""
import hashlib
import json
import re
from contextvars import ContextVar

CURRENT_REUSE = ContextVar("confirmed_project_decisions", default=())

from backend.knowledge.trace import DecisionTrace, confirmed_sources


def candidates(archive, completed_id, job_id, project_id):
    content = archive["content"]
    basis = archive.get("basis") or {}
    trace = archive.get("trace") or {}
    if not isinstance(basis, dict) or not isinstance(trace, dict) or not isinstance(basis.get("requirement_lock_sheet", {}), dict):
        return []
    sources = {**confirmed_sources(basis, {}), **basis.get("confirmed_user_sources", {})}
    reusable_sources = {source_ref(item) for item in basis.get("reused_decisions", [])}
    decisions = {d.get("id"): d for d in [*(basis.get("requirement_lock_sheet") or {}).get("decisions", []), *trace.get("decisions", [])] if isinstance(d, dict)}
    from backend.knowledge.trace import REQUIREMENT_GROUPS
    from backend.services.requirement_review import SECTIONS
    from backend.services.spec_compiler import _mask_fenced_code
    known = {r["id"] for group in REQUIREMENT_GROUPS for r in (basis.get("requirement_lock_sheet") or {}).get(group, [])}
    visible = _mask_fenced_code(content)
    result = []
    for raw in decisions.values():
        try:
            decision = DecisionTrace.model_validate(raw).model_dump()
        except ValueError:
            continue
        text, conditions = decision["text"], decision["conditions"]
        if not decision["id"].strip() or not text.strip() or len(text) + len(conditions) > 12000 or re.search(r"\bWF-", str(decision)) or not set(decision["requirement_ids"]) <= known:
            continue
        # 원래 작성 주체를 유지한다. 등록 행동을 사용자의 직접 인용으로 바꾸지 않는다.
        if decision["actor"] == "user" and not any(text in sources.get(s, "") for s in decision["sources"]):
            continue
        if not decision["sources"] or not set(decision["sources"]) <= sources.keys() | reusable_sources:
            continue
        evidence = []
        for link in trace.get("links", []):
            if not isinstance(link, dict):
                continue
            quote = link.get("quote", "")
            if decision["id"] not in link.get("decision_ids", []) or not quote or quote not in content:
                continue
            heading = next((h for h, field in SECTIONS.items() if field == link.get("section") or h == link.get("section")), None)
            marker = re.search(r"(?m)^" + re.escape(heading) + r"[ \t]*$", visible) if heading else None
            if marker is None:
                continue
            following = re.search(r"(?m)^## (?!#)", visible[marker.end():])
            end = marker.end() + following.start() if following else len(content)
            section = content[marker.end():end]
            if section.count(quote) != 1:
                continue
            start = marker.end() + section.index(quote)
            quote = quote[:2000]
            evidence.append({"item_id": link.get("item_id"), "section": link.get("section"), "quote": quote, "start": start, "end": start + len(quote)})
        if not evidence:
            continue
        result.append({"decision_id": decision["id"], "text": text, "conditions": conditions, "actor": decision["actor"],
            "job_id": job_id, "project_id": project_id, "completed_id": completed_id,
            "source_hash": hashlib.sha256(content.encode()).hexdigest(), "evidence": evidence[:3]})
    return result


def source_ref(item):
    return "project_decision:" + item["id"] + ":" + str(item["version"])


def context(items):
    return [{"source_id": source_ref(item), "text": item["text"], "conditions": item["conditions"],
             "actor": item["actor"], "completed_id": item["completed_id"]} for item in items]


def validate_requirement_sources(sheet, items, *, require_all=False):
    """선택하지 않은 공통 결정의 출처 ID를 만들어내지 못하게 한다."""
    from backend.knowledge.trace import REQUIREMENT_GROUPS
    allowed = {source_ref(item) for item in items}
    used = set()
    for group in REQUIREMENT_GROUPS:
        for requirement in getattr(sheet, group):
            refs = [requirement.source, *requirement.sources]
            used.update(refs)
            if any(ref.startswith("project_decision:") and ref not in allowed for ref in refs):
                raise ValueError("선택하지 않은 공통 결정 출처입니다.")
    if require_all and not allowed <= used:
        raise ValueError("선택한 공통 결정마다 관련 제품 요구사항의 출처를 연결하세요.")


def page(packet, offset=0):
    if type(offset) is not int or offset < 0:
        raise ValueError("조회 위치를 확인하세요.")
    rows = []
    for row in packet["rows"][offset:offset + 20]:
        if len(json.dumps([*rows, row], ensure_ascii=False).encode()) > 110000:
            break
        rows.append(row)
    return {**packet, "rows": rows, "offset": offset, "next_offset": offset + len(rows) if offset + len(rows) < len(packet["rows"]) else None}
