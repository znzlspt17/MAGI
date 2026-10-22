"""확인 가능한 산출물만 지식 노드와 관계로 변환하는 순수 함수."""

import hashlib
import json
import re

from backend.knowledge.trace import REQUIREMENT_GROUPS, confirmed_sources


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def project(job_id, state, artifacts, stage=None):
    nodes, edges, keys = [], [], {}
    actual = confirmed_sources(state, artifacts)
    actual.update(state.get("confirmed_user_sources", {}))
    requirements_stage = stage in {None, "import", "requirement_lock", "spec_compile", "checklist_critic", "review_resolution", "approve"}
    spec_stage = stage in {None, "import", "spec_compile", "checklist_critic", "review_resolution", "approve"}
    review_stage = stage in {None, "import", "checklist_critic", "review_resolution"}

    def add(key, kind, body, **attrs):
        if kind in {"requirement", "decision", "spec"}:
            attrs["scope"] = "product"
        if state.get("import_origin"):
            attrs["origin"] = "demo" if state["import_origin"].get("demo") else "imported"
        ident = digest([job_id, key, body, attrs])
        nodes.append({"id": ident, "logical_key": key, "kind": kind, "body": body, "attrs": attrs})
        keys[key] = ident
        return ident

    def edge(source, target, kind, **attrs):
        if source and target:
            edges.append({"id": digest([source, target, kind]), "source": source,
                          "target": target, "kind": kind, "attrs": attrs})

    request = state.get("original_user_request") or state.get("user_request") or artifacts.get("raw/user_request.md", "")
    if request:
        add("user_request", "input", request, actor="user", status="confirmed", source="raw/user_request.md")
    feedback = state.get("revision_feedback", "")
    if feedback:
        add("user_feedback", "input", feedback, actor="user", status="confirmed")
    sheet = state.get("requirement_lock_sheet") or {}
    if not sheet and "analysis/requirement_lock_sheet.json" in artifacts:
        sheet = json.loads(artifacts["analysis/requirement_lock_sheet.json"])
    if sheet:
        from backend.models import RequirementLockSheet
        from backend.services.workflow_constraints import validate_product_boundary
        validate_product_boundary(RequirementLockSheet.from_dict(sheet))
    for answer in sheet.get("user_answers", []):
        key = "user_answer:" + answer["question_id"]
        confirmed = actual.get(key) == answer["answer"]
        actor, status = ("user", "confirmed") if confirmed else ("llm", "proposed")
        source = add(key, "input", answer["answer"], actor=actor, status=status, question=answer.get("question", ""))
    if not requirements_stage:
        return nodes, edges
    from backend.services.project_decisions import source_ref
    for item in state.get("reused_decisions", []):
        ref = source_ref(item)
        add(ref, "decision", item["text"], actor=item["actor"], status="confirmed", conditions=item["conditions"],
            provenance="explicit_project_reuse", registry_id=item["id"], version=item["version"], completed_id=item["completed_id"], source_hash=item["source_hash"])
    for group in REQUIREMENT_GROUPS:
        for item in sheet.get(group, []):
            ident = add("req:" + item["id"], "requirement", item["text"], requirement_id=item["id"], group=group,
                        original_text=item.get("original_text", ""),
                        sources=list(dict.fromkeys(item.get("sources", []) + [item.get("source", "")])))
            for source in set(item.get("sources", []) + [item.get("source", "")]):
                edge(keys.get(source), ident, "derived")
                if source.startswith("user_answer:"):
                    edge(keys.get("answer_decision:" + source.split(":", 1)[1]), ident, "derived")
    for assumption in sheet.get("assumptions", []):
        add("assumption:" + assumption["id"], "decision", assumption["text"],
            actor="llm", status="assumption", rationale="", conditions="", risk=assumption.get("risk"))
    traces = list(sheet.get("decisions", []))
    links = []
    if spec_stage and "analysis/spec_trace.json" in artifacts:
        packet = json.loads(artifacts["analysis/spec_trace.json"])
        traces += packet.get("decisions", [])
        links = packet.get("links", [])
    decisions = {item["id"]: item for item in traces}
    for source in {ref for item in decisions.values() for ref in item["sources"]}:
        if source in actual and re.search(r":[0-9a-f]{64}$", source):
            add(source, "input", actual[source], actor="user", status="confirmed", source=source)
    for item in decisions.values():
        confirmed = item["actor"] == "user" and any(item["text"] in actual.get(source, "") for source in item["sources"])
        ident = add("decision:" + item["id"], "decision", item["text"],
                    actor="user" if confirmed else "llm", status="confirmed" if confirmed else "proposed",
                    rationale=item["rationale"], conditions=item["conditions"], sources=item["sources"],
                    requirement_ids=item["requirement_ids"], reused_node_ids=item["reused_node_ids"])
        for source in item["sources"]:
            edge(keys.get(source), ident, "evidence")
        for req in item["requirement_ids"]:
            edge(ident, keys.get("req:" + req), "derived")
        for reused in item["reused_node_ids"]:
            edge(reused, ident, "reused", rationale=item["rationale"])
    spec_path = next((p for p in ("final/FINAL_AGENT_SPEC.md", "draft/approval_candidate_spec.en.md") if p in artifacts), None) if spec_stage else None
    if spec_path:
        from backend.services.spec_compiler import _mask_fenced_code
        spec = artifacts[spec_path]
        visible = _mask_fenced_code(spec)
        # 섹션은 이전 산출물에서도 추출 가능하다. 관계는 실제 ID 표기가 있을 때만 생성한다.
        headings = {}
        for match in re.finditer(r"(?m)^(#{2,3} .+)$", visible):
            level = len(match.group(1).split(" ", 1)[0])
            headings = {key: value for key, value in headings.items() if key < level}
            headings[level] = match.group(1).lstrip("# ")
            start = match.end()
            following = re.search(r"(?m)^#{1,3} ", visible[start:])
            end = start + following.start() if following else len(spec)
            body = spec[start:end].strip()
            if not body:
                continue
            refs = re.findall(r"\b(?:REQ|REC|OPT|CON|NS)-[A-Za-z0-9_-]+\b", visible[start:end])
            ident = add("section:" + match.group(1), "spec", body, section=match.group(1),
                        title_path=" > ".join(headings.values()),
                        artifact_path=spec_path, artifact_hash=digest(spec),
                        requirement_versions=[keys["req:" + req] for req in refs if "req:" + req in keys])
            for req in refs:
                edge(keys.get("req:" + req), ident, "implemented")
        for link in links:
            if link["quote"] not in spec:
                continue
            ident = add("item:" + link["item_id"], "spec", link["quote"], section=link["section"],
                        artifact_path=spec_path, artifact_hash=digest(spec),
                        requirement_versions=[keys["req:" + req] for req in link["requirement_ids"] if "req:" + req in keys],
                        decision_versions=[keys["decision:" + ref] for ref in link["decision_ids"] if "decision:" + ref in keys])
            for req in link["requirement_ids"]:
                edge(keys.get("req:" + req), ident, "implemented")
            for decision in link["decision_ids"]:
                edge(keys.get("decision:" + decision), ident, "implemented")
    for issue in state.get("structured_issues", []) if review_stage else []:
        key = issue.get("issue_id") or digest([issue.get("checklist_id"), issue.get("problem")])
        ident = add("issue:" + key, "review", issue.get("problem", ""), **issue,
                    reviewed_artifact_hash=digest(artifacts[spec_path]) if spec_path else None)
        edge(keys.get("req:" + str(issue.get("requirement_id"))), ident, "reviewed")
        edge(keys.get("section:" + issue.get("section", "")), ident, "reviewed")
    return nodes, edges
