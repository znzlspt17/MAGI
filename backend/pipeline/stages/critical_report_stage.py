"""검토 실패 보고서 생성 단계."""

from __future__ import annotations

from typing import Any

from backend.errors import InvalidStateError
from backend.models import STATUS_CRITICAL_BLOCKED
from backend.models import WorkflowState
from backend.pipeline.context import PipelineContext


class CriticalReportStage:
    def __init__(self, context: PipelineContext) -> None:
        self.context = context

    def __call__(self, state: WorkflowState) -> dict[str, Any]:
        path = "draft/approval_candidate_spec.en.md"
        try:
            failed_draft = self.context.writer.read_text(path)
        except Exception as exc:
            raise InvalidStateError("Reviewed candidate draft is missing.") from exc
        if not failed_draft.strip():
            raise InvalidStateError("Reviewed candidate draft is missing.")
        report = self.context.critical_reporter.generate(
            state,
            writer=self.context.writer,
        )
        created = list(state.get("created_artifacts", []))
        self.context.writer.write_text(
            "critical/FAILED_AGENT_SPEC_DRAFT.en.md", failed_draft
        )
        self.context.writer.write_text("critical/CRITICAL_REPORT.ko.md", report)
        created.extend(
            ["critical/FAILED_AGENT_SPEC_DRAFT.en.md", "critical/CRITICAL_REPORT.ko.md"]
        )
        return {
            "status": STATUS_CRITICAL_BLOCKED,
            "critical_report": str(
                self.context.writer.path("critical/CRITICAL_REPORT.ko.md")
            ),
            "created_artifacts": created,
        }
