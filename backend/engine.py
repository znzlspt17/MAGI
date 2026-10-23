"""Public engine API for MAGI."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Callable
from uuid import uuid4

from backend.config import Config, VALID_WEB_SEARCH_MODES
from backend.errors import InvalidStateError, Error
from backend.infrastructure.artifact_writer import ArtifactWriter
from backend.infrastructure.evidence_registry import EvidenceRegistry
from backend.infrastructure.heartbeat import HEARTBEAT_PATH, RunHeartbeat
from backend.models import (
    STATUS_FINALIZED,
    STATUS_NEEDS_USER_INPUT,
    STATUS_PASS_PENDING_USER_APPROVAL,
    STATUS_REJECTED_BY_USER,
    State,
)
from backend.models import Result
from backend.pipeline.workflow_nodes import WorkflowNodes
from backend.pipeline.builder import build_v2_workflow
from backend.providers.llm_provider import OpenAIProvider
from backend.services.saved_answers import saved_answers
from backend.services.skill_registry import build_default_skill_registry


SUPPORTED_INPUT_EXTENSIONS = {".md", ".txt"}


class Engine:
    def __init__(
        self,
        *,
        config: Config | None = None,
        provider: OpenAIProvider | None = None,
    ) -> None:
        self.config = config or Config.default()
        self.provider = provider or OpenAIProvider()

    def generate_from_file(
        self,
        *,
        input_path: str,
        output_dir: str,
        project_dir: str | None = None,
        web_search_mode: str | None = None,
        overwrite: bool = False,
        on_progress: Callable[[dict[str, str]], None] | None = None,
    ) -> Result:
        path = Path(input_path)
        if not path.exists():
            raise FileNotFoundError(f"Input file does not exist: {input_path}")
        if path.suffix.lower() not in SUPPORTED_INPUT_EXTENSIONS:
            raise Error(
                f"Unsupported input extension '{path.suffix}'. Supported: .md, .txt"
            )
        return self.generate_from_text(
            text=path.read_text(encoding="utf-8"),
            output_dir=output_dir,
            project_dir=project_dir,
            web_search_mode=web_search_mode,
            input_source=str(path.resolve()),
            overwrite=overwrite,
            on_progress=on_progress,
        )

    def generate_from_text(
        self,
        *,
        text: str,
        output_dir: str,
        project_dir: str | None = None,
        web_search_mode: str | None = None,
        input_source: str = "direct_text",
        reused_decisions: list[dict] | None = None,
        overwrite: bool = False,
        on_progress: Callable[[dict[str, str]], None] | None = None,
    ) -> Result:
        self.config.validate()
        self._validate_web_search_mode(web_search_mode)
        self._validate_provider_credentials()
        from backend.knowledge.format_guard import require_current
        require_current(output_dir)
        writer = ArtifactWriter(output_dir, allow_overwrite=overwrite)
        writer.prepare()
        evidence = EvidenceRegistry()
        evidence.add(
            "USER_REQUEST", "Original user request was captured.", input_source
        )
        created: list[str] = []

        writer.write_text("raw/user_request.md", text)
        # 새 생성은 기존 작업의 응답 연결을 이어받지 않는다.
        from backend.infrastructure.conversation_state import PATH as conversation_path
        if writer.path(conversation_path).exists():
            writer.path(conversation_path).unlink()

        writer.write_json(
            "state/private_model_assignments.json",
            self.config.private_model_assignments(),
        )
        created.extend(
            [
                "raw/user_request.md",
                "state/private_model_assignments.json",
            ]
        )

        state = State(
            run_id=uuid4().hex[:12],
            status="DRAFT",
            user_request=text,
            original_user_request=text,
            reused_decisions=copy.deepcopy(reused_decisions or []),
            input_source=input_source,
            project_dir=str(Path(project_dir).resolve()) if project_dir else None,
            output_dir=str(Path(output_dir).resolve()),
            web_search_mode=web_search_mode or self.config.web_search,
            pipeline_version=self.config.pipeline_version,
            evidence_registry_path=str(writer.path("evidence/evidence_registry.json")),
            created_artifacts=created,
            max_critic_passes=self.config.max_critic_passes,
        )
        writer.write_json("evidence/evidence_registry.json", evidence.to_dict(), overwrite=True)
        state.created_artifacts.append("evidence/evidence_registry.json")
        self._persist_state(writer, state)
        return self._run_workflow(state, writer, evidence, on_progress=on_progress)

    def approve(
        self,
        output_dir: str,
        *,
        on_progress: Callable[[dict[str, str]], None] | None = None,
    ) -> Result:
        _notify_progress(on_progress, "approve", "started")
        writer = ArtifactWriter(output_dir, allow_overwrite=False)
        state = self._load_state(writer)
        if state.status != STATUS_PASS_PENDING_USER_APPROVAL:
            raise InvalidStateError(
                "Approval attempted before the run is ready. "
                f"Expected {STATUS_PASS_PENDING_USER_APPROVAL}, got {state.status}."
            )
        if state.user_approval_status != "PENDING":
            raise InvalidStateError("Approval candidate has not completed the latest review.")
        candidate = Path(state.approval_candidate_spec or "")
        if not candidate.exists():
            raise InvalidStateError("Approval candidate does not exist.")
        self._validate_candidate_for_approval(candidate, state)
        final_path = writer.path("final/FINAL_AGENT_SPEC.md")
        from backend.services.completed_specs import archive_completed
        if final_path.exists() and not state.latest_completed:
            raise InvalidStateError("이전 완료본의 확정 자료가 보존되지 않았습니다.")
        previous = final_path.read_bytes() if final_path.exists() else None
        previous_state = writer.read_text("state/state.json")
        content = candidate.read_text(encoding="utf-8")
        completed = archive_completed(writer, state, content)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = writer.path("final/FINAL_AGENT_SPEC.tmp")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, final_path)
        state.status = STATUS_FINALIZED
        state.user_approval_status = "APPROVED"
        state.final_agent_spec = str(final_path)
        state.latest_completed = completed
        if completed["path"] not in state.created_artifacts:
            state.created_artifacts.append(completed["path"])
        if "final/FINAL_AGENT_SPEC.md" not in state.created_artifacts:
            state.created_artifacts.append("final/FINAL_AGENT_SPEC.md")
        try:
            self._persist_state(writer, state)
        except Exception:
            if previous is None:
                final_path.unlink(missing_ok=True)
            else:
                temporary.write_bytes(previous)
                os.replace(temporary, final_path)
            writer.write_text("state/state.json", previous_state, overwrite=True)
            raise
        _notify_progress(on_progress, "approve", "completed")
        return self._result_from_state(state)

    def revise(
        self,
        *,
        output_dir: str,
        feedback_path: str,
        on_progress: Callable[[dict[str, str]], None] | None = None,
    ) -> Result:
        writer = ArtifactWriter(output_dir, allow_overwrite=True)
        state = self._load_state(writer)
        from backend.services.completed_specs import require_conversation, archive_completed, restore_completed_cache
        require_conversation(writer)
        if state.status == STATUS_FINALIZED:
            restore_completed_cache(writer, state)
            state.latest_completed = archive_completed(writer, state)
        feedback = Path(feedback_path).read_text(encoding="utf-8")
        state.status = STATUS_REJECTED_BY_USER
        state.user_approval_status = "REJECTED"
        state.revision_feedback = feedback.strip()
        state.revision_history.append(state.revision_feedback)
        state.resume_stage = "interview"
        writer.write_text("raw/revision_feedback.md", feedback, overwrite=True)
        evidence = EvidenceRegistry.from_dict(
            writer.read_json("evidence/evidence_registry.json")
        )
        evidence.add(
            "USER_REQUEST", "User revision feedback was captured.", feedback_path
        )

        # 새 요청은 체크포인트에 먼저 저장한다. 실패해도 기존 초안과 포인터를 보존한다.
        state.structured_issues = []
        state.critic_pass_count = 0
        state.diagnosed_keys = []
        state.resolution_stop = False
        self._persist_state(writer, state)
        workflow_state = copy.deepcopy(state)
        workflow_state.final_agent_spec = None
        return self._run_workflow(
            workflow_state, writer, evidence, on_progress=on_progress
        )

    def answer(
        self,
        output_dir: str,
        *,
        answers: list[dict],
        on_progress: Callable[[dict[str, str]], None] | None = None,
    ) -> Result:
        """Inject user answers to blocking questions and resume the pipeline."""
        writer = ArtifactWriter(output_dir, allow_overwrite=True)
        state = self._load_state(writer)

        from backend.services.completed_specs import require_conversation
        require_conversation(writer)

        from backend.models import RequirementLockSheet

        pending_questions = list(state.blocking_questions)
        is_review_answer = state.awaiting_input_reason == "review"
        artifact_sheet = self._read_lock_sheet_artifact(writer)
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

        normalized_answers = _validate_answers(answers, pending_questions, state.question_forms)
        existing_answers = {
            item.question_id: item
            for item in saved_answers(
                state.to_dict(),
                legacy_lock_sheet=artifact_sheet,
                pending_questions=pending_questions,
            )
        }
        state.confirmed_user_sources.update({"user_answer:" + item.question_id: item.answer for item in normalized_answers})
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
        if remaining_questions:
            state.blocking_questions = remaining_questions
            state.status = STATUS_NEEDS_USER_INPUT
            state.resume_stage = None
            writer.write_json(
                "analysis/requirement_lock_sheet.json", sheet.to_dict(), overwrite=True
            )
            writer.write_text(
                "analysis/requirement_lock_sheet.ko.md",
                sheet.to_markdown(),
                overwrite=True,
            )
            writer.write_text(
                "analysis/05_blocking_questions.ko.md",
                "# 차단 질문\n\n"
                + "\n".join(f"- {item}" for item in state.blocking_questions)
                + "\n",
                overwrite=True,
            )
            self._persist_state(writer, state)
            _notify_progress(on_progress, "await_user", "completed")
            return self._result_from_state(state)
        writer.write_json(
            "analysis/requirement_lock_sheet.json", sheet.to_dict(), overwrite=True
        )
        writer.write_text(
            "analysis/requirement_lock_sheet.ko.md", sheet.to_markdown(), overwrite=True
        )

        # Reset compile/critic state
        if not is_review_answer:
            state.structured_issues = []
        state.critic_pass_count = 0
        state.diagnosed_keys = []
        state.resolution_stop = False
        state.status = STATUS_NEEDS_USER_INPUT
        state.blocking_questions = pending_questions
        state.resume_stage = None

        # 제공자 기반 인터뷰가 실패하기 전에 사용자 답변을 저장한다.
        self._persist_state(writer, state)
        workflow_state = copy.deepcopy(state)
        workflow_state.blocking_questions = remaining_questions
        workflow_state.awaiting_input_reason = None
        workflow_state.resume_stage = "requirement_lock_stage" if is_review_answer else "interview"
        workflow_state.final_agent_spec = None

        evidence = EvidenceRegistry.from_dict(
            writer.read_json("evidence/evidence_registry.json")
        )
        evidence.add(
            "USER_REQUEST",
            "User answers to blocking questions were incorporated.",
            output_dir,
        )
        return self._run_workflow(
            workflow_state, writer, evidence, on_progress=on_progress
        )

    def status(self, output_dir: str) -> Result:
        writer = ArtifactWriter(output_dir, allow_overwrite=False)
        state = self._load_state(writer)
        return self._result_from_state(state)

    def retry(self, output_dir: str, *, checkpoint: dict, on_progress=None) -> Result:
        """저장된 단계 결과를 복원하고 다음 단계부터 재개한다."""
        from backend.knowledge.runtime import restore_artifacts
        from backend.services.workflow_recovery import validate_checkpoint
        from backend.services.completed_specs import require_conversation
        value = validate_checkpoint(checkpoint)
        writer = ArtifactWriter(output_dir, allow_overwrite=True)
        require_conversation(writer)
        state_data = {**value["state"], "output_dir": str(writer.output_dir)}
        artifacts = {**value["artifacts"], "state/state.json": json.dumps(state_data, ensure_ascii=False)}
        restore_artifacts(writer.output_dir, artifacts)
        state = self._load_state(writer)
        if state.resume_stage is None:
            self._persist_state(writer, state)
            _notify_progress(on_progress, value["stage"], "completed")
            return self._result_from_state(state)
        evidence = EvidenceRegistry.from_dict(writer.read_json("evidence/evidence_registry.json"))
        return self._run_workflow(state, writer, evidence, on_progress=on_progress)

    def _run_workflow(
        self,
        state: State,
        writer: ArtifactWriter,
        evidence: EvidenceRegistry,
        *,
        on_progress: Callable[[dict[str, str]], None] | None = None,
    ) -> Result:
        skills = build_default_skill_registry()
        nodes = WorkflowNodes(
            writer=writer,
            config=self.config,
            provider=self.provider,
            skills=skills,
            evidence=evidence,
        )
        from backend.services.workflow_recovery import save_checkpoint
        save_checkpoint(writer, evidence, "workflow_entry", state.to_workflow_state(), {})
        workflow = build_v2_workflow(nodes, on_progress=on_progress,
                                    checkpoint=lambda stage, before, result: save_checkpoint(
                                        writer, evidence, stage, before, result))

        if HEARTBEAT_PATH not in state.created_artifacts:
            state.created_artifacts.append(HEARTBEAT_PATH)
        previous_draft: str | None = None
        draft_path = "draft/approval_candidate_spec.en.md"
        try:
            previous_draft = writer.read_text(draft_path)
        except Exception:
            pass
        heartbeat = RunHeartbeat(writer=writer, state=state)
        heartbeat.start()
        try:
            from backend.services.project_decisions import CURRENT_REUSE
            reuse_token = CURRENT_REUSE.set(state.reused_decisions)
            try:
                final_state = State.from_workflow_state(workflow.invoke(state.to_workflow_state()))
            finally:
                CURRENT_REUSE.reset(reuse_token)
            heartbeat.stop(final_status=final_state.status)
        except Exception as exc:
            # 저장을 마친 해결 판단과 연결된 최신 초안은 실패 시에도 보존한다.
            committed_draft = False
            recovery_draft = previous_draft
            try:
                from backend.knowledge.runtime import CURRENT
                from backend.services.review_resolution import text_hash
                runtime = CURRENT.get()
                records = writer.read_json("state/state.json").get("resolution_history", [])
                saved_hash = runtime.resolved_draft_hash if runtime is not None else records[-1]["draft_hash"] if records else None
                committed_draft = saved_hash == text_hash(writer.read_text(draft_path))
                if not committed_draft and saved_hash:
                    resolved_draft = writer.read_text("review/resolved_draft.en.md")
                    if text_hash(resolved_draft) == saved_hash:
                        recovery_draft = resolved_draft
            except (Error, OSError, ValueError, KeyError, TypeError):
                pass
            if recovery_draft is not None and not committed_draft:
                try:
                    writer.write_text(draft_path, recovery_draft, overwrite=True)
                except Exception:
                    pass
            heartbeat.stop(exc=exc)
            _notify_progress(on_progress, "workflow", "failed")
            raise
        writer.write_json(
            "evidence/evidence_registry.json", evidence.to_dict(), overwrite=True
        )
        if "evidence/evidence_registry.json" not in final_state.created_artifacts:
            final_state.created_artifacts.append("evidence/evidence_registry.json")
        final_state.evidence_registry_path = str(
            writer.path("evidence/evidence_registry.json")
        )
        final_state.resume_stage = None
        self._persist_state(writer, final_state)
        _notify_progress(on_progress, "workflow", "completed")
        return self._result_from_state(final_state)

    def _persist_state(self, writer: ArtifactWriter, state: State) -> None:
        if "state/state.json" not in state.created_artifacts:
            state.created_artifacts.append("state/state.json")
        from backend.knowledge.runtime import CURRENT
        runtime = CURRENT.get()
        if runtime is not None:
            runtime.commit("state", state.to_dict())
        writer.write_json("state/state.json", state.to_dict(), overwrite=True)

    def _load_state(self, writer: ArtifactWriter) -> State:
        from backend.models import RequirementLockSheet
        from backend.knowledge.format_guard import require_current
        require_current(writer.output_dir)
        path = writer.path("state/state.json")
        if not path.exists():
            raise InvalidStateError(f"MAGI state file does not exist: {path}")
        try:
            state = State.from_dict(writer.read_json("state/state.json"))
            if any(not all(key in record for key in ("decision_key", "feedback_hash", "question_id", "question")) for record in state.review_questions):
                raise InvalidStateError("Review contract is invalid. Start a new generation.")
            for issue in state.structured_issues:
                from backend.models import IssuePacket
                IssuePacket.from_dict(issue)
            if state.requirement_lock_sheet is not None:
                from backend.services.workflow_constraints import validate_locked_sources
                validate_locked_sources(RequirementLockSheet.from_dict(state.requirement_lock_sheet), state.to_dict())
            if state.latest_completed:
                from backend.services.completed_specs import load_completed
                load_completed(writer, state.latest_completed.get("id"))
            return self._hydrate_original_user_request(writer, state)
        except InvalidStateError:
            raise
        except Exception as exc:
            raise InvalidStateError(f"Malformed MAGI state file: {path}. Start a new generation.") from exc

    @staticmethod
    def _hydrate_original_user_request(
        writer: ArtifactWriter, state: State
    ) -> State:
        """이전 실행 기록도 원문 산출물을 우선해 불변 요청 문맥을 복구한다."""
        try:
            raw_request = writer.read_text("raw/user_request.md")
        except Exception:
            raw_request = ""
        if raw_request.strip():
            state.original_user_request = raw_request
            state.user_request = raw_request
        elif state.original_user_request.strip():
            state.user_request = state.original_user_request
        elif not state.original_user_request:
            state.original_user_request = state.user_request
        if not isinstance(state.revision_history, list):
            state.revision_history = []
        else:
            state.revision_history = [
                item for item in state.revision_history if isinstance(item, str)
            ]
        return state

    @staticmethod
    def _read_lock_sheet_artifact(writer: ArtifactWriter) -> dict | None:
        try:
            data = writer.read_json("analysis/requirement_lock_sheet.json")
        except Exception:
            return None
        if isinstance(data, dict):
            from backend.models import RequirementLockSheet
            RequirementLockSheet.from_dict(data)
            return data
        return None

    def _result_from_state(self, state: State) -> Result:
        questions_path = None
        if state.status == STATUS_NEEDS_USER_INPUT:
            p = Path(state.output_dir) / "analysis" / "05_blocking_questions.ko.md"
            if p.exists():
                questions_path = str(p)
        return Result(
            status=state.status,
            output_dir=state.output_dir,
            approval_candidate_path=state.approval_candidate_spec,
            final_spec_path=state.final_agent_spec,
            critical_report_path=state.critical_report,
            state_path=str(Path(state.output_dir) / "state" / "state.json"),
            heartbeat_path=str(Path(state.output_dir) / HEARTBEAT_PATH),
            questions_path=questions_path,
        )

    def _validate_candidate_for_approval(
        self, candidate: Path, state: State
    ) -> None:
        """Reject externally modified candidates that no longer meet blocking checks."""
        from backend.models import (
            count_unresolved_required,
            parse_issue_list,
        )
        from backend.models import RequirementLockSheet
        from backend.services.checklist import run_deterministic_checks

        candidate_text = candidate.read_text(encoding="utf-8")
        from backend.services.spec_compiler import SpecCompiler

        if not SpecCompiler.english_only(candidate_text):
            raise InvalidStateError("Approval candidate must be English-only.")
        stored_issues = parse_issue_list(state.structured_issues)
        if count_unresolved_required(stored_issues):
            raise InvalidStateError(
                "Approval candidate still has unresolved required review issues."
            )
        if state.blocking_questions or any(issue.resolution_kind == "user_decision" and issue.status != "resolved" for issue in stored_issues):
            raise InvalidStateError("Approval candidate still has unresolved required review issues.")
        sheet = RequirementLockSheet.from_dict(state.requirement_lock_sheet).require_validated()

        from backend.services.workflow_constraints import validate_product_boundary, validate_locked_sources
        validate_locked_sources(sheet, state.to_dict())
        try:
            validate_product_boundary(sheet, [candidate_text])
        except ValueError:
            raise InvalidStateError("Requirement lock contract is invalid. Start a new generation.") from None
        issues = run_deterministic_checks(candidate_text, sheet)
        if count_unresolved_required(issues):
            raise InvalidStateError(
                "Approval candidate no longer satisfies blocking checks."
            )

    def _validate_provider_credentials(self) -> None:
        self.config.validate()
        self.provider.validate_credentials()

    def _validate_web_search_mode(self, mode: str | None) -> None:
        if mode is None:
            return
        if mode not in VALID_WEB_SEARCH_MODES:
            raise Error(
                f"Invalid web_search_mode '{mode}'. Allowed values are: auto, on, off."
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
        if any(key in item for key in ("form_version", "selected_option_ids", "custom_text")):
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
        result.append(QAItem(question_id=question_id, question=question, answer=answer, selection=selection))
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
