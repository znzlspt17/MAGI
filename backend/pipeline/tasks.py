"""그래프 작업의 실제 업무 함수. 작업마다 전달 클래스나 별도 구성 계층을 만들지 않는다."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.errors import InvalidStateError
from backend.infrastructure.prompt_messages import messages
from backend.infrastructure.prompts import load_prompt
from backend.infrastructure.provider_call import complete_with_usage
from backend.infrastructure.web_search import (
    should_research,
    summarize_web_research,
    web_search,
)
from backend.models import (
    STATUS_ANALYZING,
    STATUS_COMPILING,
    STATUS_CRITICAL_BLOCKED,
    STATUS_CRITIQUING,
    STATUS_NEEDS_USER_INPUT,
    STATUS_PASS_PENDING_USER_APPROVAL,
    STATUS_RESEARCHING,
    InterviewResponse,
    InterviewResult,
    IssuePacket,
    LockResponse,
    QAItem,
    RequirementLockSheet,
    ReviewResponse,
    WorkflowState,
    count_unresolved_blocking,
    count_unresolved_required,
    parse_issue_list,
)
from backend.services.checklist_critic import ChecklistCritic
from backend.services.critical_reporter import CriticalReporter
from backend.services.interviewer import SpecInterviewer
from backend.services.requirement_lock_builder import RequirementLockBuilder
from backend.services.review_questions import collect_review_questions
from backend.services.review_resolution import (
    confirmed_basis,
    defect_identity,
    text_hash,
    validate_resolutions,
)
from backend.services.spec_compiler import SpecCompiler
from backend.services.workflow_constraints import validate_locked_sources


@dataclass
class WorkflowTasks:
    writer: Any
    runtime: Any
    config: Any
    provider: Any
    skills: Any
    evidence: Any
    interviewer: SpecInterviewer = field(default_factory=SpecInterviewer)
    lock_builder: RequirementLockBuilder = field(default_factory=RequirementLockBuilder)
    critic: ChecklistCritic = field(default_factory=ChecklistCritic)

    def __post_init__(self):
        self.compiler = SpecCompiler(
            config=self.config, provider=self.provider, skills=self.skills
        )
        self.critical_reporter = CriticalReporter(skills=self.skills)

    def project_context(self, state):
        manifest = {"file_count": 0, "files": []}
        self.writer.write_json("context/project_manifest.json", manifest)
        return {}

    def spec_compile(self, state: WorkflowState) -> dict[str, Any]:
        created = list(state.get("created_artifacts", []))
        try:
            manifest: dict[str, Any] = self.writer.read_json(
                "context/project_manifest.json"
            )
        except Exception:
            manifest = {}
        sheet_data = state.get("requirement_lock_sheet")
        from backend.services.workflow_constraints import validate_locked_sources

        sheet = validate_locked_sources(
            RequirementLockSheet.from_dict(sheet_data).require_validated(), state
        )
        raw_issues = state.get("structured_issues", [])
        issues = parse_issue_list({"issues": raw_issues}) if raw_issues else None
        path = "draft/approval_candidate_spec.en.md"
        previous_spec = ""
        if issues or state.get("revision_feedback") or state.get("revision_history"):
            try:
                previous_spec = self.writer.read_text(path)
            except Exception:
                previous_spec = ""
        spec = self.compiler.compile(
            sheet,
            manifest,
            issues,
            user_request=str(
                state.get("original_user_request") or state.get("user_request", "")
            ),
            previous_spec=previous_spec,
            revision_feedback=str(state.get("revision_feedback", "")),
            revision_history=list(state.get("revision_history", [])),
            writer=self.writer,
        )
        self.writer.write_text(path, spec, overwrite=True)
        if path not in created:
            created.append(path)
        return {
            "status": STATUS_COMPILING,
            "approval_candidate_spec": path,
            "created_artifacts": created,
        }

    def compose_candidate(self, state: WorkflowState) -> dict[str, Any]:
        issues = parse_issue_list(state.get("structured_issues", []))
        if (
            state.get("blocking_questions")
            or count_unresolved_required(issues)
            or any(
                issue.resolution_kind == "user_decision" and issue.status != "resolved"
                for issue in issues
            )
        ):
            raise InvalidStateError(
                "Approval candidate still has unresolved required review issues."
            )
        created = list(state.get("created_artifacts", []))
        path = "draft/approval_candidate_spec.en.md"
        try:
            spec = self.writer.read_text(path)
        except Exception:
            spec = ""
        if not spec or not self.compiler.english_only(spec):
            raise InvalidStateError("Reviewed candidate is missing or invalid.")
        if path not in created:
            created.append(path)
        # 변경 검토는 안내 기능이며 승인 후보 검증 결과를 바꾸지 않는다.
        from backend.services.change_review import (
            CURRENT_REVIEW,
            digest,
            normalize,
            review_candidate,
        )

        try:
            review_candidate(self, state, spec)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "change review unavailable exception_type=%s", type(exc).__name__
            )
            try:
                self.writer.write_json(
                    CURRENT_REVIEW,
                    {
                        "status": "failed",
                        "reason": "analysis_failed",
                        "changes": [],
                        "sources": [],
                        "after_hash": digest(normalize(spec)),
                        "analysed": 0,
                        "remaining": None,
                    },
                )
            except Exception:
                logging.getLogger(__name__).warning(
                    "change review failure could not be saved"
                )
        return {
            "status": STATUS_PASS_PENDING_USER_APPROVAL,
            "approval_candidate_spec": path,
            "user_approval_status": "PENDING",
            "final_agent_spec": None,
            "created_artifacts": created,
        }

    def interview(self, state: WorkflowState) -> dict[str, Any]:
        created = list(state.get("created_artifacts", []))
        try:
            manifest: dict[str, Any] = self.writer.read_json(
                "context/project_manifest.json"
            )
        except Exception:
            manifest = {}
        route = self.config.model_routing[self.interviewer.agent_id]
        provider = self.provider

        def complete(messages: list[dict[str, str]]) -> InterviewResponse:
            return complete_with_usage(
                self.writer,
                provider,
                messages,
                model=route.model,
                stage="interview",
                temperature=0,
            )

        result = self.interviewer.run(state, manifest, provider_messages_fn=complete)
        files = {
            "analysis/01_intent_parse.ko.md": f"# 의도 분석\n\n요청 유형: {result.request_type}\n",
            "analysis/03_scope_classification.ko.md": "# 범위 분류\n\n- v2 파이프라인: Requirement Lock Sheet에서 관리됩니다.\n",
            "analysis/04_initial_assumptions.ko.md": "# 초기 가정\n\n"
            + "\n".join(f"- {a}" for a in result.assumptions)
            + "\n",
            "analysis/05_blocking_questions.ko.md": "# 차단 질문\n\n"
            + (
                "\n".join(f"- {q}" for q in result.blocking_questions)
                if result.blocking_questions
                else "- 없음\n"
            ),
        }
        for path, content in files.items():
            self.writer.write_text(path, content, overwrite=True)
            if path not in created:
                created.append(path)
        for assumption in result.assumptions:
            self.evidence.add("AGENT_ASSUMPTION", assumption, "interview")
        return {
            "status": STATUS_ANALYZING,
            "request_type": result.request_type,
            "assumptions": result.assumptions,
            "blocking_questions": result.blocking_questions,
            "question_forms": result.question_forms,
            "awaiting_input_reason": "interview" if result.blocking_questions else None,
            "interview_pre_answers": [item.to_dict() for item in result.pre_answers],
            "_interview_direction_changing": result.direction_changing_pending,
            "created_artifacts": created,
        }

    def requirement_lock_stage(self, state: WorkflowState) -> dict[str, Any]:
        created = list(state.get("created_artifacts", []))
        try:
            manifest: dict[str, Any] = self.writer.read_json(
                "context/project_manifest.json"
            )
        except Exception:
            manifest = {}
        route = self.config.model_routing[self.lock_builder.agent_id]
        provider = self.provider

        def complete(messages: list[dict[str, str]]) -> LockResponse:
            return complete_with_usage(
                self.writer,
                provider,
                messages,
                model=route.model,
                stage="requirement_lock",
                temperature=0,
            )

        interview = InterviewResult(
            request_type=state.get("request_type", "feature"),
            blocking_questions=list(state.get("blocking_questions", [])),
            assumptions=list(state.get("assumptions", [])),
            pre_answers=_latest_answers(
                _existing_answers(state)
                + [
                    QAItem.from_dict(item)
                    for item in state.get("interview_pre_answers", [])
                    if isinstance(item, dict)
                ]
            ),
        )
        sheet = self.lock_builder.build(
            state,
            manifest,
            interview,
            provider_messages_fn=complete,
            runtime=self.runtime,
        )
        sheet = _merge_existing_sheet(sheet, state)
        self.writer.write_json("analysis/requirement_lock_sheet.json", sheet.to_dict())
        self.writer.write_text(
            "analysis/requirement_lock_sheet.ko.md", sheet.to_markdown()
        )
        self.writer.write_text(
            "analysis/02_requirement_lock.ko.md", sheet.to_markdown()
        )
        created.extend(
            [
                "analysis/requirement_lock_sheet.json",
                "analysis/requirement_lock_sheet.ko.md",
                "analysis/02_requirement_lock.ko.md",
            ]
        )
        return {
            "status": STATUS_ANALYZING,
            "requirement_lock": sheet.to_markdown(),
            "requirement_lock_sheet": sheet.to_dict(),
            "created_artifacts": created,
        }

    def checklist_critic(self, state: WorkflowState) -> dict[str, Any]:
        created = list(state.get("created_artifacts", []))
        spec = self.writer.read_text("draft/approval_candidate_spec.en.md")
        sheet_data = state.get("requirement_lock_sheet")
        from backend.services.workflow_constraints import validate_locked_sources

        sheet = validate_locked_sources(
            RequirementLockSheet.from_dict(sheet_data).require_validated(), state
        )
        route = self.config.model_routing[self.critic.agent_id]
        provider = self.provider

        def complete(messages: list[dict[str, str]]) -> ReviewResponse:
            return complete_with_usage(
                self.writer,
                provider,
                messages,
                model=route.model,
                stage="checklist_critic",
                temperature=0,
            )

        issues = self.critic.critique(
            spec,
            sheet,
            provider_messages_fn=complete,
            user_request=str(
                state.get("original_user_request") or state.get("user_request", "")
            ),
            previous_issues=state.get("structured_issues", []),
            revision_feedback=str(state.get("revision_feedback", "")),
            revision_history=list(state.get("revision_history", [])),
        )
        history = list(state.get("review_history", []))
        issue_data = [item.to_dict() for item in issues]
        passes = int(state.get("critic_pass_count", 0)) + 1
        history.append(
            {"review_round": len(history) + 1, "pass": passes, "issues": issue_data}
        )
        self.writer.write_json(
            "review/checklist_issues.json",
            {
                "pass": passes,
                "unresolved_blocking": count_unresolved_blocking(issues),
                "unresolved_required": count_unresolved_required(issues),
                "issues": issue_data,
            },
            overwrite=True,
        )
        if "review/checklist_issues.json" not in created:
            created.append("review/checklist_issues.json")
        return {
            "status": STATUS_CRITIQUING,
            "structured_issues": issue_data,
            "critic_pass_count": passes,
            "blocking_questions": [],
            "awaiting_input_reason": None,
            "review_history": history,
            "created_artifacts": created,
        }

    def review_resolution(self, state):
        sheet = validate_locked_sources(
            RequirementLockSheet.from_dict(
                state.get("requirement_lock_sheet")
            ).require_validated(),
            state,
        )
        issues = parse_issue_list(state.get("structured_issues", []))
        selected = [
            issue
            for issue in issues
            if issue.status != "resolved"
            and (
                issue.severity in {"blocking", "major"}
                or issue.resolution_kind == "user_decision"
                or issue.decision_answer_id
            )
        ]
        history = list(state.get("resolution_history", []))
        prior = (
            {
                defect_identity(IssuePacket.from_dict(item)): item
                for item in history[-1]["issues"]
            }
            if history
            else {}
        )
        repeated = {
            defect_identity(issue)
            for issue in selected
            if state.get("critic_pass_count", 0) > 1 and defect_identity(issue) in prior
        }
        diagnosed = set(state.get("diagnosed_keys", []))
        to_diagnose = repeated - diagnosed
        exhausted = repeated & diagnosed
        stop = bool(exhausted)
        draft = self.writer.read_text("draft/approval_candidate_spec.en.md")
        basis = confirmed_basis(state, sheet.to_dict())
        pending_resolution = [
            issue for issue in selected if defect_identity(issue) not in exhausted
        ]
        reconfirm = set()
        if pending_resolution:
            canonical = {
                "issues": [issue.to_dict() for issue in pending_resolution],
                "confirmed_basis": basis,
                "previous_resolutions": history[-1:]
                if state.get("critic_pass_count", 0) > 1
                else [],
                "review_questions": state.get("review_questions", []),
                "diagnose_keys": sorted(to_diagnose),
                "draft_hash": text_hash(draft),
            }
            payload = messages(
                load_prompt("review_resolution"),
                basis["user_request"],
                json.dumps(canonical, ensure_ascii=False),
                ("Draft specification", draft),
            )
            packet = complete_with_usage(
                self.writer,
                self.provider,
                payload,
                model=self.config.model_routing["critic"].model,
                stage="review_resolution",
                temperature=0,
            )
            reconfirm = validate_resolutions(
                packet,
                pending_resolution,
                basis,
                state.get("review_questions", []),
                state,
            )
            diagnosed.update(to_diagnose)
        if stop:
            for issue in selected:
                if defect_identity(issue) in prior:
                    previous = prior[defect_identity(issue)]
                    for key in (
                        "resolution_kind",
                        "resolution_reason",
                        "missing_information",
                        "required_change",
                        "decision_question",
                        "basis_refs",
                    ):
                        setattr(issue, key, previous[key])
        questions, pending = collect_review_questions(
            issues, state, len(history) + 1, reconfirm_keys=reconfirm
        )
        # 검토 원본과 다른 해결 분류도 동일 초안에 연결해 별도 이력으로 남긴다.
        data = [issue.to_dict() for issue in issues]
        if pending:
            action = "ask_user"
        elif selected and (
            stop
            or state.get("critic_pass_count", 0) >= state.get("max_critic_passes", 3)
        ):
            action = "stop"
        else:
            action = "repair" if selected else "approve"
        record = {
            "review_round": len(history) + 1,
            "pass": state.get("critic_pass_count", 0),
            "draft_hash": text_hash(draft),
            "diagnosed_keys": sorted(to_diagnose) if pending_resolution else [],
            "issues": data,
            "action": action,
        }
        history.append(record)
        reviews = [dict(entry) for entry in state.get("review_history", [])]
        if reviews:
            reviews[-1].update(issues=data, draft_hash=record["draft_hash"])
        self.writer.write_text("review/resolved_draft.en.md", draft, overwrite=True)
        self.writer.write_json("review/resolution.json", record, overwrite=True)
        self.writer.write_text(
            "analysis/05_blocking_questions.ko.md",
            "# 요구사항 확인 필요\n\n"
            + ("\n".join("- " + question for question in pending) or "- 없음")
            + "\n",
            overwrite=True,
        )
        created = list(
            dict.fromkeys(
                [
                    *state.get("created_artifacts", []),
                    "review/resolution.json",
                    "review/resolved_draft.en.md",
                    "analysis/05_blocking_questions.ko.md",
                ]
            )
        )
        result = {
            "review_history": reviews,
            "structured_issues": data,
            "resolution_history": history,
            "diagnosed_keys": sorted(diagnosed),
            "resolution_stop": stop,
            "review_questions": questions,
            "blocking_questions": pending,
            "question_forms": {
                q["question_id"]: q["form"]
                for q in questions
                if "form" in q
                and any(p.startswith("[" + q["question_id"] + "]") for p in pending)
            },
            "awaiting_input_reason": "review" if pending else None,
            "created_artifacts": created,
        }

        return result

    def await_user(self, state: WorkflowState) -> dict[str, Any]:
        return {
            "status": STATUS_NEEDS_USER_INPUT,
            "blocking_questions": list(state.get("blocking_questions", [])),
            "awaiting_input_reason": state.get("awaiting_input_reason"),
            "question_forms": state.get("question_forms", {}),
            "review_questions": list(state.get("review_questions", [])),
        }

    def critical_report(self, state: WorkflowState) -> dict[str, Any]:
        path = "draft/approval_candidate_spec.en.md"
        try:
            failed_draft = self.writer.read_text(path)
        except Exception as exc:
            raise InvalidStateError("Reviewed candidate draft is missing.") from exc
        if not failed_draft.strip():
            raise InvalidStateError("Reviewed candidate draft is missing.")
        report = self.critical_reporter.generate(state)
        created = list(state.get("created_artifacts", []))
        self.writer.write_text("critical/FAILED_AGENT_SPEC_DRAFT.en.md", failed_draft)
        self.writer.write_text("critical/CRITICAL_REPORT.ko.md", report)
        created.extend(
            ["critical/FAILED_AGENT_SPEC_DRAFT.en.md", "critical/CRITICAL_REPORT.ko.md"]
        )
        return {
            "status": STATUS_CRITICAL_BLOCKED,
            "critical_report": str("critical/CRITICAL_REPORT.ko.md"),
            "created_artifacts": created,
        }

    def web_research(self, state: WorkflowState) -> dict[str, Any]:
        created = list(state.get("created_artifacts", []))
        mode = state.get("web_search_mode", "auto")
        sources: list[dict[str, Any]] = []
        performed = should_research(state.get("user_request", ""), mode)
        research = {
            "mode": mode,
            "search_method": "duckduckgo_html_links",
            "performed": performed,
            "outcome": "skipped",
            "reason": "disabled" if mode == "off" else "not_required",
            "query": state.get("user_request", "") if performed else "",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "sources": [],
            "result_count": 0,
        }
        failure = None
        if performed:
            try:
                sources = web_search(state.get("user_request", ""), max_results=5)
                research.update(
                    outcome="links_found" if sources else "no_results",
                    reason="search_results",
                )
            except Exception as exc:
                research.update(outcome="failed", reason="search_failed")
                failure = exc
        research.update(sources=sources, result_count=len(sources))
        self.writer.write_json("research/research_record.json", research)
        if failure is not None and mode == "on":
            failure.research_record = research
            raise failure
        for source in sources:
            self.evidence.add(
                "WEB_SOURCE",
                source.get("title", "Web source"),
                source.get("url", ""),
                metadata={"query": source.get("query", "")},
            )
        self.writer.write_json("research/web_sources.json", {"sources": sources})
        self.writer.write_text(
            "research/web_research_summary.ko.md", summarize_web_research(sources, mode)
        )
        created.extend(
            [
                "research/web_sources.json",
                "research/web_research_summary.ko.md",
                "research/research_record.json",
            ]
        )
        return {
            "status": STATUS_RESEARCHING,
            "research": research,
            "created_artifacts": created,
        }


def _existing_answers(state: WorkflowState):
    data = state.get("requirement_lock_sheet")
    return RequirementLockSheet.from_dict(data).user_answers if data else []


def _latest_answers(answers: list[QAItem]) -> list[QAItem]:
    """동일 질문은 이번 인터뷰에서 확인한 최신 답변만 잠금에 전달한다."""
    latest: dict[str, QAItem] = {}
    for answer in answers:
        latest[answer.question_id] = answer
    return list(latest.values())


def _merge_existing_sheet(
    rebuilt: RequirementLockSheet, state: WorkflowState
) -> RequirementLockSheet:
    """새 잠금 결과를 기준으로 하되 같은 ID의 원문만 보존한다."""
    data = state.get("requirement_lock_sheet")
    if not data:
        return rebuilt
    existing = RequirementLockSheet.from_dict(data)
    rebuilt.lock_id = existing.lock_id
    for field in (
        "mandatory_requirements",
        "recommended_requirements",
        "optional_requirements",
        "non_scope",
        "constraints",
    ):
        prior = {item.id: item for item in getattr(existing, field)}
        for item in getattr(rebuilt, field):
            previous = prior.get(item.id)
            if previous is not None and not item.original_text:
                item.original_text = previous.original_text or previous.text
    latest_answers = {item.question_id: item for item in existing.user_answers}
    latest_answers.update({item.question_id: item for item in rebuilt.user_answers})
    rebuilt.user_answers = list(latest_answers.values())
    merged_assumptions = {item.id: item for item in existing.assumptions}
    merged_assumptions.update({item.id: item for item in rebuilt.assumptions})
    rebuilt.assumptions = list(merged_assumptions.values())
    rebuilt.source_refs = list(
        dict.fromkeys(existing.source_refs + rebuilt.source_refs)
    )
    return rebuilt
