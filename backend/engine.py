"""웹 명령을 그래프 입력으로 바꾼다. 파일 저장과 독립 실행 API는 제공하지 않는다."""

from __future__ import annotations

import copy
import hashlib
from typing import Callable

from backend.config import Config
from backend.errors import InvalidStateError
from backend.infrastructure.evidence_registry import EvidenceRegistry
from backend.models import (
    State,
    STATUS_FINALIZED,
    STATUS_NEEDS_USER_INPUT,
    STATUS_PASS_PENDING_USER_APPROVAL,
)
from backend.providers.llm_provider import ChatModelProvider
from backend.services.saved_answers import saved_answers
from backend.services.skill_registry import SkillRegistry


class Engine:
    def __init__(self, documents, runtime, *, config=None, provider=None):
        self.documents, self.runtime = documents, runtime
        self.config = config or Config()
        self.provider = provider or ChatModelProvider(meter=runtime.meter)

    def load(self):
        from backend.services.completed_specs import load_completed

        data = self.documents.workflow_snapshot().values
        if not data or data.get("workflow_schema") != 1:
            raise InvalidStateError("현재 그래프 상태를 확인할 수 없습니다.")
        state = State.from_dict(data)
        if state.latest_completed:
            load_completed(self.documents, state.latest_completed["id"])
        self.documents.state = state.to_dict()
        return state

    def execute(self, action, payload=None, *, on_progress=None):
        writer = self.documents
        if action == "generate":
            self.config.validate()
            state = State(
                run_id=writer.job_id,
                status="DRAFT",
                user_request=payload,
                original_user_request=payload,
                reused_decisions=copy.deepcopy(
                    self.runtime.job.get("reused_decisions", [])
                ),
                max_critic_passes=self.config.max_critic_passes,
                web_search_mode="off",
            )
            evidence = EvidenceRegistry()
            evidence.add(
                "USER_REQUEST", "Original user request was captured.", "user_request"
            )
            writer.write_text("raw/user_request.md", payload, overwrite=False)
        else:
            state = self.load()
            if action == "retry":
                saved = writer.workflow_snapshot()
                if (not saved.next and state.status == STATUS_FINALIZED) or (
                    any(t.interrupts for t in saved.tasks)
                    and "retry" not in state.allowed_actions
                ):
                    return state
            evidence = EvidenceRegistry.from_dict(
                writer.read_json("evidence/evidence_registry.json")
            )
            if action in {"message", "revise", "continue"}:
                if not isinstance(payload, str) or not payload.strip():
                    raise InvalidStateError("수정 의견을 입력해주세요.")
                state.revision_feedback = payload.strip()
                state.revision_history.append(state.revision_feedback)
                state.structured_issues = []
                state.blocking_questions = []
                state.awaiting_input_reason = None
                state.critic_pass_count = 0
                state.diagnosed_keys = []
                state.resolution_stop = False
                state.final_agent_spec = None
                state.user_approval_status = "PENDING"
                action = "message" if action == "continue" else action
            elif action == "answer":
                state = self._answer(state, payload)
            elif action == "approve":
                if (
                    not isinstance(payload, dict)
                    or payload.get("candidate_hash") != state.candidate_hash
                ):
                    raise InvalidStateError("승인 후보가 변경되었습니다.")
                if state.status != STATUS_PASS_PENDING_USER_APPROVAL:
                    raise InvalidStateError("검토를 통과한 승인 후보가 필요합니다.")
                candidate = writer.read_text("draft/approval_candidate_spec.en.md")
                self._validate_candidate_for_approval(candidate, state)
                if (
                    hashlib.sha256(candidate.encode()).hexdigest()
                    != state.candidate_hash
                ):
                    raise InvalidStateError("승인 후보가 변경되었습니다.")
        from backend.pipeline.tasks import WorkflowTasks
        from backend.pipeline.agent_workflow import AgentWorkflow

        writer.state = state.to_dict()
        nodes = WorkflowTasks(
            writer=writer,
            runtime=self.runtime,
            config=self.config,
            provider=self.provider,
            skills=SkillRegistry(),
            evidence=evidence,
        )
        return AgentWorkflow(self, nodes, writer, evidence, on_progress).run(
            state, action=action
        )

    def _answer(self, state, answers):
        writer = self.documents
        from backend.models import RequirementLockSheet

        pending_questions = list(state.blocking_questions)
        is_review_answer = state.awaiting_input_reason == "review"
        sheet = (
            RequirementLockSheet.from_dict(state.requirement_lock_sheet)
            if state.requirement_lock_sheet
            else RequirementLockSheet.build_fallback(
                request_type=state.request_type or "feature",
                request_summary=state.original_user_request or state.user_request,
                blocking_questions=pending_questions,
                assumptions=state.assumptions,
            )
        )

        normalized_answers = _validate_answers(
            answers, pending_questions, state.question_forms
        )
        existing_answers = {
            item.question_id: item
            for item in saved_answers(
                state.to_dict(),
            )
        }
        state.confirmed_user_sources.update(
            {
                "user_answer:" + item.question_id: item.answer
                for item in normalized_answers
            }
        )
        existing_answers.update({item.question_id: item for item in normalized_answers})
        sheet.user_answers = list(existing_answers.values())
        all_answers = list(existing_answers.values())
        sheet.unresolved_questions = [
            q
            for q in sheet.unresolved_questions
            if not _question_is_answered(
                q,
                {item.question_id for item in all_answers},
                all_answers,
            )
        ]
        state.requirement_lock_sheet = sheet.to_dict()
        remaining_questions = [
            q
            for q in pending_questions
            if not _question_is_answered(
                q,
                {item.question_id for item in all_answers},
                all_answers,
            )
        ]
        writer.write_json("analysis/requirement_lock_sheet.json", sheet.to_dict())
        writer.write_text("analysis/requirement_lock_sheet.ko.md", sheet.to_markdown())
        if remaining_questions:
            state.blocking_questions = remaining_questions
            return state

        # Reset compile/critic state
        if not is_review_answer:
            state.structured_issues = []
        state.critic_pass_count = 0
        state.diagnosed_keys = []
        state.resolution_stop = False
        state.status = STATUS_NEEDS_USER_INPUT
        state.blocking_questions = pending_questions

        state.blocking_questions = remaining_questions
        state.awaiting_input_reason = None
        state.final_agent_spec = None
        return state

    def finalize(self, state):
        from backend.services.completed_specs import archive_completed

        current = State.from_dict(state)
        content = self.documents.read_text("draft/approval_candidate_spec.en.md")
        self._validate_candidate_for_approval(content, current)
        if hashlib.sha256(content.encode()).hexdigest() != current.candidate_hash:
            raise InvalidStateError("승인 후보가 변경되었습니다.")
        with self.documents.store.transaction():
            completed = archive_completed(self.documents, current, content)
            self.documents.write_text("final/FINAL_AGENT_SPEC.md", content)
        return {
            **state,
            "status": STATUS_FINALIZED,
            "user_approval_status": "APPROVED",
            "latest_completed": completed,
            "final_agent_spec": "final/FINAL_AGENT_SPEC.md",
            "created_artifacts": list(
                dict.fromkeys([*state.get("created_artifacts", []), completed["path"]])
            ),
        }

    def _validate_candidate_for_approval(
        self, candidate_text: str, state: State
    ) -> None:
        """Reject externally modified candidates that no longer meet blocking checks."""
        from backend.models import (
            count_unresolved_required,
            parse_issue_list,
        )
        from backend.models import RequirementLockSheet
        from backend.services.checklist import run_deterministic_checks

        from backend.services.spec_compiler import SpecCompiler

        if not SpecCompiler.english_only(candidate_text):
            raise InvalidStateError("Approval candidate must be English-only.")
        stored_issues = parse_issue_list(state.structured_issues)
        if count_unresolved_required(stored_issues):
            raise InvalidStateError(
                "Approval candidate still has unresolved required review issues."
            )
        if state.blocking_questions or any(
            issue.resolution_kind == "user_decision" and issue.status != "resolved"
            for issue in stored_issues
        ):
            raise InvalidStateError(
                "Approval candidate still has unresolved required review issues."
            )
        sheet = RequirementLockSheet.from_dict(
            state.requirement_lock_sheet
        ).require_validated()

        from backend.services.workflow_constraints import (
            validate_product_boundary,
            validate_locked_sources,
        )

        validate_locked_sources(sheet, state.to_dict())
        try:
            validate_product_boundary(sheet, [candidate_text])
        except ValueError:
            raise InvalidStateError(
                "Requirement lock contract is invalid. Start a new generation."
            ) from None
        issues = run_deterministic_checks(candidate_text, sheet)
        if count_unresolved_required(issues):
            raise InvalidStateError(
                "Approval candidate no longer satisfies blocking checks."
            )


def _validate_answers(answers: list[dict], questions: list[str], forms=None):
    from backend.models import QAItem

    if not isinstance(answers, list) or not answers:
        raise InvalidStateError("At least one non-empty answer is required.")
    result: list[QAItem] = []
    seen = set()
    for item in answers:
        if not isinstance(item, dict):
            raise InvalidStateError("Each answer must be an object.")
        question_id = str(item.get("question_id", "")).strip()
        question = str(item.get("question", "")).strip()
        answer = str(item.get("answer", "")).strip()
        selection = None
        if question_id in seen:
            raise InvalidStateError("Duplicate answer question ID.")
        seen.add(question_id)
        if any(
            key in item
            for key in ("form_version", "selected_option_ids", "custom_text")
        ):
            from backend.services.question_forms import selected_answer

            form = (forms or {}).get(question_id)
            if not form or not any(p.startswith(f"[{question_id}]") for p in questions):
                raise InvalidStateError("Question form is no longer pending.")
            try:
                answer, selection = selected_answer(item, form)
            except ValueError as error:
                raise InvalidStateError(str(error)) from error
            question = form["question"]
        if not question_id or not answer:
            raise InvalidStateError("Each answer requires question_id and answer.")
        if questions and not any(
            f"[{question_id}]" in pending or (question and question in pending)
            for pending in questions
        ):
            raise InvalidStateError(
                f"Answer does not match a pending question: {question_id}"
            )
        result.append(
            QAItem(
                question_id=question_id,
                question=question,
                answer=answer,
                selection=selection,
            )
        )
    return result


def _question_is_answered(question: str, ids: set[str], answers: list[object]) -> bool:
    if any(f"[{question_id}]" in question for question_id in ids):
        return True
    return any(
        getattr(answer, "question", "") and getattr(answer, "question") in question
        for answer in answers
    )


def _notify_progress(
    callback: Callable[[dict[str, str]], None] | None,
    stage: str,
    state: str,
) -> None:
    """Deliver non-essential progress updates without affecting the engine run."""
    if callback is None:
        return
    try:
        callback({"stage": stage, "state": state})
    except Exception:
        return
