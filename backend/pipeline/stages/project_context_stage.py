"""프로젝트 컨텍스트 수집 단계."""

from __future__ import annotations
from pathlib import Path
from typing import Any
from backend.infrastructure.project_scan import (
    scan_project_folder,
    summarize_project_context,
)
from backend.models import WorkflowState
from backend.pipeline.context import PipelineContext


class ProjectContextStage:
    def __init__(self, context: PipelineContext) -> None:
        self.context = context

    def __call__(self, state: WorkflowState) -> dict[str, Any]:
        project_dir = state.get("project_dir")
        created = list(state.get("created_artifacts", []))
        if project_dir:
            manifest = scan_project_folder(project_dir)
            summary = summarize_project_context(manifest)
            self.context.evidence.add(
                "PROJECT_FILE",
                "Project folder manifest was collected read-only.",
                str(Path(project_dir).resolve()),
                metadata={"file_count": manifest["file_count"]},
            )
        else:
            manifest = {
                "root": None,
                "file_count": 0,
                "files": [],
                "ignored_directories": [],
                "ignored_secret_patterns": [],
            }
            summary = (
                "# 프로젝트 컨텍스트 요약\n\n- 프로젝트 폴더가 제공되지 않았습니다.\n"
            )
        self.context.writer.write_json("context/project_manifest.json", manifest)
        self.context.writer.write_text("context/project_summary.ko.md", summary)
        created.extend(
            ["context/project_manifest.json", "context/project_summary.ko.md"]
        )
        return {
            "project_manifest_path": str(
                self.context.writer.path("context/project_manifest.json")
            ),
            "created_artifacts": created,
        }
