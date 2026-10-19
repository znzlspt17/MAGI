"""검토 후 해결 판단·반복 진단·질문 전환을 하나의 저장 경계로 처리한다."""

import json

from backend.infrastructure.prompt_messages import messages
from backend.infrastructure.prompts import load_prompt
from backend.infrastructure.provider_call import complete_with_usage
from backend.models import IssuePacket, RequirementLockSheet, parse_issue_list
from backend.services.review_questions import collect_review_questions
from backend.services.review_resolution import confirmed_basis, defect_identity, text_hash, validate_resolutions
from backend.services.workflow_constraints import validate_locked_sources


class ReviewResolutionStage:
    def __init__(self, context):
        self.context = context

    def __call__(self, state):
        sheet = validate_locked_sources(RequirementLockSheet.from_dict(state.get("requirement_lock_sheet")).require_validated(), state)
        issues = parse_issue_list(state.get("structured_issues", []))
        selected = [issue for issue in issues if issue.status != "resolved" and
                    (issue.severity in {"blocking", "major"} or issue.resolution_kind == "user_decision" or issue.decision_answer_id)]
        history = list(state.get("resolution_history", []))
        prior = {defect_identity(IssuePacket.from_dict(item)): item for item in history[-1]["issues"]} if history else {}
        repeated = {defect_identity(issue) for issue in selected if state.get("critic_pass_count", 0) > 1 and defect_identity(issue) in prior}
        diagnosed = set(state.get("diagnosed_keys", []))
        to_diagnose = repeated - diagnosed
        exhausted = repeated & diagnosed
        stop = bool(exhausted)
        draft = self.context.writer.read_text("draft/approval_candidate_spec.en.md")
        basis = confirmed_basis(state, sheet.to_dict())
        pending_resolution = [issue for issue in selected if defect_identity(issue) not in exhausted]
        reconfirm = set()
        if pending_resolution:
            canonical = {"issues": [issue.to_dict() for issue in pending_resolution], "confirmed_basis": basis,
                         "previous_resolutions": history[-1:] if state.get("critic_pass_count", 0) > 1 else [],
                         "review_questions": state.get("review_questions", []),
                         "diagnose_keys": sorted(to_diagnose), "draft_hash": text_hash(draft)}
            payload = messages(load_prompt("review_resolution"), basis["user_request"], json.dumps(canonical, ensure_ascii=False),
                               ("Draft specification", draft))
            packet = complete_with_usage(self.context.writer, self.context.provider, payload,
                model=self.context.config.model_routing["critic"].model, stage="review_resolution", temperature=0)
            reconfirm = validate_resolutions(packet, pending_resolution, basis, state.get("review_questions", []), state)
            diagnosed.update(to_diagnose)
        if stop:
            for issue in selected:
                if defect_identity(issue) in prior:
                    previous = prior[defect_identity(issue)]
                    for key in ("resolution_kind", "resolution_reason", "missing_information", "required_change", "decision_question", "basis_refs"):
                        setattr(issue, key, previous[key])
        questions, pending = collect_review_questions(issues, state, len(history) + 1, reconfirm_keys=reconfirm)
        # 검토 원본과 다른 해결 분류도 동일 초안에 연결해 별도 이력으로 남긴다.
        data = [issue.to_dict() for issue in issues]
        if pending:
            action = "ask_user"
        elif selected and (stop or state.get("critic_pass_count", 0) >= state.get("max_critic_passes", 3)):
            action = "stop"
        else:
            action = "repair" if selected else "approve"
        record = {"review_round": len(history) + 1, "pass": state.get("critic_pass_count", 0),
                  "draft_hash": text_hash(draft), "diagnosed_keys": sorted(to_diagnose) if pending_resolution else [],
                  "issues": data, "action": action}
        history.append(record)
        reviews = [dict(entry) for entry in state.get("review_history", [])]
        if reviews:
            reviews[-1].update(issues=data, draft_hash=record["draft_hash"])
        self.context.writer.write_text("review/resolved_draft.en.md", draft, overwrite=True)
        self.context.writer.write_json("review/resolution.json", record, overwrite=True)
        self.context.writer.write_text("analysis/05_blocking_questions.ko.md",
            "# 요구사항 확인 필요\n\n" + ("\n".join("- " + question for question in pending) or "- 없음") + "\n", overwrite=True)
        created = list(dict.fromkeys([*state.get("created_artifacts", []), "review/resolution.json", "review/resolved_draft.en.md", "analysis/05_blocking_questions.ko.md"]))
        result = {"review_history": reviews, "structured_issues": data, "resolution_history": history, "diagnosed_keys": sorted(diagnosed),
                "resolution_stop": stop, "review_questions": questions, "blocking_questions": pending,
                "question_forms": {q["question_id"]: q["form"] for q in questions if "form" in q and any(p.startswith("[" + q["question_id"] + "]") for p in pending)},
                "awaiting_input_reason": "review" if pending else None, "created_artifacts": created}

        from backend.knowledge.runtime import CURRENT
        if CURRENT.get() is None and state.get("run_id"):
            from backend.models import MagiState
            checkpoint = MagiState.from_workflow_state({**state, **result})
            checkpoint.resume_stage = "spec_compile" if record["action"] == "repair" else None
            self.context.writer.write_json("state/magi_state.json", checkpoint.to_dict(), overwrite=True)
        return result
