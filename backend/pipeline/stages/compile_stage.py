"""명세 초안 컴파일 단계."""

from __future__ import annotations
from typing import Any
from backend.models import parse_issue_list
from backend.models import STATUS_COMPILING
from backend.models import RequirementLockSheet
from backend.models import WorkflowState
from backend.pipeline.context import PipelineContext


class CompileStage:
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
        sheet_data = state.get("requirement_lock_sheet")
        from backend.services.workflow_constraints import validate_locked_sources
        sheet = validate_locked_sources(RequirementLockSheet.from_dict(sheet_data).require_validated(), state)
        raw_issues = state.get("structured_issues", [])
        issues = parse_issue_list({"issues": raw_issues}) if raw_issues else None
        path = "draft/approval_candidate_spec.en.md"
        previous_spec = ""
        if issues or state.get("revision_feedback") or state.get("revision_history"):
            try:
                previous_spec = self.context.writer.read_text(path)
            except Exception:
                previous_spec = ""
        spec = self.context.compiler.compile(
            sheet,
            manifest,
            issues,
            user_request=str(
                state.get("original_user_request") or state.get("user_request", "")
            ),
            previous_spec=previous_spec,
            revision_feedback=str(state.get("revision_feedback", "")),
            revision_history=list(state.get("revision_history", [])),
            writer=self.context.writer,
        )
        self.context.writer.write_text(path, spec, overwrite=True)
        if path not in created:
            created.append(path)
        return {
            "status": STATUS_COMPILING,
            "approval_candidate_spec": str(self.context.writer.path(path)),
            "created_artifacts": created,
        }
