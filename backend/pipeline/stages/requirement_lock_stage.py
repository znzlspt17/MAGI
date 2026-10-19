"""요구사항 잠금 시트 생성 단계."""

from __future__ import annotations
from typing import Any
from backend.models import InterviewResult
from backend.models import QAItem
from backend.models import STATUS_ANALYZING
from backend.models import WorkflowState
from backend.pipeline.context import PipelineContext
from backend.models import RequirementLockSheet
from backend.infrastructure.provider_call import complete_with_usage
from backend.models import LockResponse


class RequirementLockStage:
    def __init__(self, context: PipelineContext) -> None:
        self.context = context

    def __call__(self, state: WorkflowState) -> dict[str, Any]:
        created = list(state.get("created_artifacts", []))
        try:
            manifest: dict[str, Any] = self.context.writer.read_json(
                "context/project_manifest.json"
            )
        except Exception:
            manifest = {}
        route = self.context.config.model_routing[self.context.lock_builder.agent_id]
        provider = self.context.provider

        def complete(messages: list[dict[str, str]]) -> LockResponse:
            return complete_with_usage(
                self.context.writer,
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
        sheet = self.context.lock_builder.build(
            state,
            manifest,
            interview,
            provider_messages_fn=complete,
            allow_fallback=False,
        )
        sheet = _merge_existing_sheet(sheet, state)
        self.context.writer.write_json(
            "analysis/requirement_lock_sheet.json", sheet.to_dict()
        )
        self.context.writer.write_text(
            "analysis/requirement_lock_sheet.ko.md", sheet.to_markdown()
        )
        self.context.writer.write_text(
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
