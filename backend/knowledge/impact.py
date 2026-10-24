"""화면 표시 한도와 독립적으로 현재 명세의 기록된 검토 경로를 조회한다."""

import json

from backend.knowledge.projection import digest


READY = {"PASS_PENDING_USER_APPROVAL", "FINALIZED"}
GROUPS = ("mandatory_requirements", "recommended_requirements", "optional_requirements", "constraints", "non_scope")


def impact_context(store, job_id, node_id=None):
    state = store.state(job_id)
    with store.transaction(mode="read") as conn:
        job = conn.execute("SELECT data FROM jobs WHERE id=%s", (job_id,)).fetchone()
        if not job:
            raise KeyError(job_id)
        if state.get("status") not in READY or job["data"].get("status") not in READY:
            raise ValueError("승인 후보가 준비된 작업에서 변경 영향을 검토할 수 있습니다.")
        path = "final/FINAL_AGENT_SPEC.md" if state["status"] == "FINALIZED" else "draft/approval_candidate_spec.en.md"
        source_hash = digest(store.documents(job_id).read_text(path))
        rows = conn.execute("SELECT id,logical_key,kind,body,attrs FROM nodes WHERE job_id=%s AND active "
            "AND (kind IN ('requirement','decision') AND attrs->>'scope'='product' "
            "OR kind='spec' AND attrs->>'artifact_hash'=%s "
            "OR kind='review' AND attrs->>'reviewed_artifact_hash'=%s) ORDER BY id",
            (job_id, source_hash, source_hash)).fetchall()
        nodes = {row["id"]: dict(row) for row in rows}
        sheet = state.get("requirement_lock_sheet") or {}
        requirements = {item["id"]: item for group in GROUPS for item in sheet.get(group, [])}
        node = nodes.get(node_id) if node_id else None
        if node_id and (not node or node["kind"] != "requirement" or
                        requirements.get(node["attrs"].get("requirement_id"), {}).get("text") != node["body"]):
            raise ValueError("현재 기준 명세와 일치하는 요구사항을 선택하세요.")
        edges = conn.execute("SELECT source,target,kind FROM edges WHERE source=ANY(%s) AND target=ANY(%s) "
            "AND kind IN ('derived','implemented','reviewed') ORDER BY source,target,kind", (list(nodes), list(nodes))).fetchall()
    paths = recorded_paths(node_id, nodes, edges) if node_id else []
    basis = {"id": digest([job_id, source_hash, node_id, sorted(nodes), edges]), "job_id": job_id,
             "source_hash": source_hash, "node_id": node_id, "status": state["status"]}
    return {"basis": basis, "node": node, "nodes": nodes, "edges": edges, "recorded": paths}


def recorded_paths(node_id, nodes, edges):
    found = {}

    def add(target, route, kind):
        if target == node_id:
            return
        value = found.setdefault(target, {"target": brief(nodes[target]), "paths": []})
        # 경로에는 이동에 필요한 이름만 담고 본문은 해당 항목에서 조회한다.
        entry = {"kind": kind, "nodes": [{**brief(nodes[ident]), "body": ""} for ident in route]}
        if entry not in value["paths"]:
            value["paths"].append(entry)

    direct_specs = set()
    for edge in edges:
        if edge["source"] == node_id and edge["kind"] in {"implemented", "reviewed"}:
            target = edge["target"]
            if nodes[target]["kind"] in {"spec", "review"}:
                add(target, [node_id, target], "direct")
                if nodes[target]["kind"] == "spec":
                    direct_specs.add(target)
    decisions = {edge["source"] for edge in edges if edge["target"] == node_id and edge["kind"] == "derived"
                 and nodes[edge["source"]]["kind"] == "decision"}
    for edge in edges:
        source, target = edge["source"], edge["target"]
        if source in direct_specs and edge["kind"] == "reviewed" and nodes[target]["kind"] == "review":
            add(target, [node_id, source, target], "spec_review")
        if source in decisions and edge["kind"] == "implemented" and nodes[target]["kind"] == "spec":
            add(target, [node_id, source, target], "shared_decision")
    return [found[key] for key in sorted(found)]


def brief(node):
    return {"id": node["id"], "kind": node["kind"], "body": node["body"][:240],
            "section": node["attrs"].get("section", "")[:160], "requirement_id": node["attrs"].get("requirement_id", "")[:100]}


def impact_page(context, offset=0):
    if type(offset) is not int or offset < 0 or offset % 20:
        raise ValueError("조회 위치가 올바르지 않습니다.")
    records = context["recorded"]
    page = [{**item, "paths": item["paths"][:5], "path_total": len(item["paths"])} for item in records[offset:offset + 20]]
    result = {"basis": context["basis"], "node": brief(context["node"]) if context["node"] else None,
            "recorded": page, "total": len(records), "offset": offset,
            "has_more": offset + 20 < len(records), "next_offset": offset + 20,
            "message": "기록된 연결도 변경의 영향이 확정됐다는 뜻은 아닙니다." if records else
                       "기록된 연결을 찾지 못했습니다. 추가 영향이 없다는 뜻은 아닙니다."}
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 110_000:
        # 대상은 모두 보존하고 경로의 미리보기만 줄여 전송 한도를 지킨다.
        for item in page:
            item["paths"] = [{"kind": path["kind"], "nodes": [
                {**node, "section": node["section"][:32], "requirement_id": node["requirement_id"][:32]}
                for node in path["nodes"]]} for path in item["paths"][:1]]
    return result
