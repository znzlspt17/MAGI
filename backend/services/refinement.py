"""고정 루브릭의 점수 개선을 추적하고 대응하는 최고점 초안을 복원한다."""
from copy import deepcopy
import hashlib

from backend.errors import InvalidStateError
from backend.services.rubric import digest, require_approval_evaluation, summary

DRAFT = "draft/approval_candidate_spec.ko.md"
# 초안에 종속된 추적 근거도 같은 라운드로 복원한다.
DOCUMENTS = ("analysis/spec_trace.json", "analysis/implementation_plan.json", "analysis/spec_blocks.json")


def record_round(writer, state, config):
    evaluation = state["rubric_evaluation"]
    previous = state.get("refinement", {})
    current = deepcopy(previous) if previous.get("rubric_hash") == evaluation["rubric_hash"] else {
        "rubric_hash": evaluation["rubric_hash"], "round": 0, "stale": 0, "best_score": 0, "cycle": 1}
    token = digest([evaluation, state["critic_pass_count"], current["cycle"]])
    if current.get("last_token") == token:
        return current
    current["round"] += 1
    path = f"review/refinement/{current['rubric_hash']}/{current['cycle']}/{current['round']}.json"
    snapshot = {"spec": writer.read_text(DRAFT), "evaluation": evaluation,
        "issues": state["structured_issues"], "resolution": state["resolution_history"][-1],
        "documents": {name: writer.read_json(name) for name in DOCUMENTS if writer.exists(name)}}
    if hashlib.sha256(snapshot["spec"].encode()).hexdigest() != evaluation["draft_hash"]:
        raise InvalidStateError("검토 초안이 변경되었습니다.")
    improved = evaluation["score"] > current["best_score"]
    current["stale"] = 0 if improved else current["stale"] + 1
    current["termination"] = ("max_score" if evaluation["score"] == 10 else
        "patience" if current["stale"] >= config.refinement_patience else
        "round_budget" if current["round"] >= config.max_critic_passes else "")
    snapshot["resolution"] = {**snapshot["resolution"], "action": "ask_user" if state.get("blocking_questions") else
        "approve" if current["termination"] else "repair"}
    writer.write_json(path, snapshot)
    if improved:
        current.update(best_score=evaluation["score"], best_path=path,
            best_round=current["round"], best_cycle=current["cycle"], best_hash=digest(snapshot))
    current["last_token"] = token
    return current


def restore_best(writer, state, sheet):
    current = state.get("refinement", {})
    if not current.get("termination") or current.get("rubric_hash") != state["rubric"]["rubric_hash"]:
        raise InvalidStateError("종료된 최신 명세 평가가 필요합니다.")
    snapshot = writer.read_json(current["best_path"])
    if digest(snapshot) != current["best_hash"]:
        raise InvalidStateError("최고점 후보 보존본이 변경되었습니다.")
    restored = {**state, "rubric_evaluation": snapshot["evaluation"],
        "structured_issues": snapshot["issues"]}
    require_approval_evaluation(restored, sheet, snapshot["spec"])
    writer.write_text(DRAFT, snapshot["spec"], overwrite=True)
    for name, value in snapshot["documents"].items():
        writer.write_json(name, value)
    writer.write_json("review/resolution.json", snapshot["resolution"])
    writer.write_text("review/resolved_draft.ko.md", snapshot["spec"], overwrite=True)
    from backend.services.rubric import save_evaluation
    save_evaluation(writer, snapshot["evaluation"])
    return {"rubric_evaluation": snapshot["evaluation"], "structured_issues": snapshot["issues"],
        "rubric_summary": summary(state["rubric"], snapshot["evaluation"]),
        "refinement": {**current, "selected": True}, "approval_acceptance": {}}


def public_review(state):
    """스키마 검증을 마친 구조화 필드만 작업 조회에 공개한다."""
    evaluation = state.get("rubric_evaluation", {})
    rubric = state.get("rubric", {})
    if not evaluation or evaluation.get("rubric_hash") != rubric.get("rubric_hash") or "score" not in evaluation:
        return {}
    verdicts = {item["rubric_id"]: item for item in evaluation["verdicts"]}
    current = state.get("refinement", {})
    return {"score": evaluation["score"], "score_reason": evaluation["score_reason"],
        "round": current.get("round", 0), "selected_round": current.get("best_round", 0),
        "selected_cycle": current.get("best_cycle", 1), "termination": current.get("termination", ""),
        "requires_acceptance": evaluation["score"] < 10 or any(item.get("status") != "resolved" for item in state.get("structured_issues", [])),
        "evaluation_hash": digest(evaluation), "revision_directives": evaluation["revision_directives"],
        "remaining_issues": [{key: item[key] for key in ("issue_id", "severity", "problem", "required_change")}
            for item in state.get("structured_issues", []) if item.get("status") != "resolved"],
        "items": [{"rubric_id": item["rubric_id"], "requirement_id": item["requirement_id"],
            "condition": item["condition"], "importance": item["importance"], "basis": [{key: entry[key] for key in ("reference", "quote")} for entry in item["basis"]],
            **{key: verdicts[item["rubric_id"]][key] for key in
                ("verdict", "section", "quote", "reason", "evidence_kind")}}
            for item in rubric["items"]]}


def needs_upgrade(state):
    from backend.services.rubric import POLICY_VERSION
    return state.get("status") == "PASS_PENDING_USER_APPROVAL" and state.get("rubric", {}).get("policy_version") != POLICY_VERSION
