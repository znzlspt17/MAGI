"""승인 전에 작업 참조와 의존관계를 검증하고 같은 자료로 명세를 조립한다."""
from typing import Any, NoReturn

from backend.errors import SpecCompilationError
from backend.services.change_review import digest, normalize


PATH = "analysis/implementation_plan.json"
CHECKS = {"acceptance_criteria", "test_plan", "manual_verification_checklist"}


def prepare_plan(draft, sheet):
    def fail(message: str) -> NoReturn:
        raise SpecCompilationError(["implementation_order: " + message], check="implementation_plan")

    groups = {item.id: group for group in ("mandatory_requirements", "recommended_requirements", "optional_requirements", "constraints") for item in getattr(sheet, group)}
    sources = {b.item_id: {"section": name, **b.model_dump()} for name in type(draft).model_fields
               if name not in {"decisions", "implementation_order", "out_of_scope"} for b in getattr(draft, name)}
    raw = [t.model_dump() for t in draft.implementation_order]
    tasks = {t["item_id"]: t for t in raw}
    if not raw or len(tasks) != len(raw) or any(not key.strip() for key in tasks):
        fail("비어 있지 않은 고유한 작업 ID를 사용하고 작업을 하나 이상 포함하세요.")
    for task in raw:
        refs = task["requirement_ids"]
        if not refs or len(set(refs)) != len(refs) or not set(refs) <= groups.keys():
            fail("작업은 알려진 제품 요구사항만 참조하고 non_scope 또는 WF ID를 참조하지 마세요.")
        scopes = {"required" if groups[r] in {"mandatory_requirements", "constraints"} else "recommended" if groups[r] == "recommended_requirements" else "optional" for r in refs}
        if len(scopes) != 1:
            fail("필수, 권장, 선택 작업을 각각 분리하세요.")
        task["scope"] = next(iter(scopes))
        if not task["title"].strip() or not task["text"].strip():
            fail("작업 제목과 설명은 비어 있을 수 없습니다.")
        deps = task["depends_on"]
        if len(set(deps)) != len(deps) or task["item_id"] in deps or not set(deps) <= tasks.keys():
            fail("선행 작업은 자기 자신을 제외한 고유하고 알려진 작업이어야 합니다.")
        for field, verification in (("spec_item_ids", False), ("completion_item_ids", True)):
            values = task[field]
            if not values or len(set(values)) != len(values) or any(v not in sources or (sources[v]["section"] in CHECKS) != verification for v in values):
                fail("각 참조에 알려진 동작 블록과 검증 블록을 사용하세요.")
    if not {r.id for r in sheet.mandatory_requirements} <= {r for t in raw for r in t["requirement_ids"]}:
        fail("모든 필수 요구사항을 구현 작업에 포함하세요.")
    if any(t["scope"] == "required" and any(tasks[d]["scope"] != "required" for d in t["depends_on"]) for t in raw):
        fail("필수 작업은 선택 또는 권장 작업에 의존할 수 없습니다.")
    ordered: list[dict[str, Any]] = []
    while len(ordered) < len(raw):
        done = {t["item_id"] for t in ordered}
        ready = next((t for t in raw if t["item_id"] not in done and set(t["depends_on"]) <= done), None)
        if ready is None:
            fail("순환 작업 의존성은 허용하지 않습니다.")
        ordered.append(ready)
    for task in ordered:
        scope_label = {"required": "필수", "recommended": "권장", "optional": "선택"}[task["scope"]]
        task["rendered"] = (f'### [{task["item_id"]}] {task["title"]}\n\n{task["text"]}\n\n'
            f'- 범위: {scope_label}\n- 요구사항: ' + ", ".join(task["requirement_ids"]) +
            '\n- 선행 작업: ' + (", ".join(task["depends_on"]) or "없음") +
            '\n- 명세 블록: ' + ", ".join(task["spec_item_ids"]) +
            '\n- 완료 조건: ' + ", ".join(f'{ref} ({sources[ref]["section"]})' for ref in task["completion_item_ids"]))
    used = {ref for task in ordered for field in ("spec_item_ids", "completion_item_ids") for ref in task[field]}
    # 작업에 연결되지 않은 검증 본문도 승인본의 별도 확인 항목으로 보존한다.
    return {"version": 1, "tasks": ordered, "sources": [s for ident, s in sources.items() if ident in used or s["section"] in CHECKS]}


def valid_plan(value, content):
    try:
        sources = {s["item_id"]: s for s in value["sources"]}
        return (value.get("version") == 1 and value.get("source_hash") == digest(normalize(content))
                and bool(value["tasks"]) and all(t["rendered"] and t["rendered"] in content
                    and all(r in sources for field in ("spec_item_ids", "completion_item_ids") for r in t[field]) for t in value["tasks"])
                and all(s["text"] and s["text"].rstrip() in content for s in sources.values()))
    except (KeyError, TypeError, AttributeError):
        return False
