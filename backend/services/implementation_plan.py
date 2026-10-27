"""승인 전에 작업 참조와 의존관계를 검증하고 같은 자료로 명세를 조립한다."""

from backend.errors import SpecCompilationError
from backend.services.change_review import digest, normalize


PATH = "analysis/implementation_plan.json"
CHECKS = {"acceptance_criteria", "test_plan", "manual_verification_checklist"}


def prepare_plan(draft, sheet):
    def fail(message):
        raise SpecCompilationError(["implementation_order: " + message], check="implementation_plan")

    groups = {item.id: group for group in ("mandatory_requirements", "recommended_requirements", "optional_requirements", "constraints") for item in getattr(sheet, group)}
    sources = {b.item_id: {"section": name, **b.model_dump()} for name in type(draft).model_fields
               if name not in {"decisions", "implementation_order", "out_of_scope"} for b in getattr(draft, name)}
    raw = [t.model_dump() for t in draft.implementation_order]
    tasks = {t["item_id"]: t for t in raw}
    if not raw or len(tasks) != len(raw) or any(not key.strip() for key in tasks):
        fail("Use unique nonempty task IDs and include at least one task.")
    for task in raw:
        refs = task["requirement_ids"]
        if not refs or len(set(refs)) != len(refs) or not set(refs) <= groups.keys():
            fail("Tasks must reference known product requirements, never non_scope or WF IDs.")
        scopes = {"required" if groups[r] in {"mandatory_requirements", "constraints"} else "recommended" if groups[r] == "recommended_requirements" else "optional" for r in refs}
        if len(scopes) != 1:
            fail("Split required, recommended and optional work into separate tasks.")
        task["scope"] = next(iter(scopes))
        if not task["title"].strip() or not task["text"].strip():
            fail("Task title and description must be nonempty.")
        deps = task["depends_on"]
        if len(set(deps)) != len(deps) or task["item_id"] in deps or not set(deps) <= tasks.keys():
            fail("Predecessors must be unique known tasks other than the task itself.")
        for field, verification in (("spec_item_ids", False), ("completion_item_ids", True)):
            values = task[field]
            if not values or len(set(values)) != len(values) or any(v not in sources or (sources[v]["section"] in CHECKS) != verification for v in values):
                fail("Use known behavior blocks and verification blocks for their respective references.")
    if not {r.id for r in sheet.mandatory_requirements} <= {r for t in raw for r in t["requirement_ids"]}:
        fail("Cover every mandatory requirement with implementation tasks.")
    if any(t["scope"] == "required" and any(tasks[d]["scope"] != "required" for d in t["depends_on"]) for t in raw):
        fail("Required work cannot depend on optional or recommended work.")
    ordered = []
    while len(ordered) < len(raw):
        done = {t["item_id"] for t in ordered}
        ready = next((t for t in raw if t["item_id"] not in done and set(t["depends_on"]) <= done), None)
        if ready is None:
            fail("Cyclic task dependencies are not allowed.")
        ordered.append(ready)
    for task in ordered:
        task["rendered"] = (f'### [{task["item_id"]}] {task["title"]}\n\n{task["text"]}\n\n'
            f'- Scope: {task["scope"]}\n- Requirements: ' + ", ".join(task["requirement_ids"]) +
            '\n- Predecessors: ' + (", ".join(task["depends_on"]) or "None") +
            '\n- Specification blocks: ' + ", ".join(task["spec_item_ids"]) +
            '\n- Completion conditions: ' + ", ".join(f'{ref} ({sources[ref]["section"]})' for ref in task["completion_item_ids"]))
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
