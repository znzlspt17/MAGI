"""웹 리서치 단계."""

from __future__ import annotations
from typing import Any
from backend.infrastructure.web_search import (
    should_research,
    summarize_web_research,
    web_search,
)
from backend.models import STATUS_RESEARCHING
from backend.models import WorkflowState
from backend.pipeline.context import PipelineContext


class WebResearchStage:
    def __init__(self, context: PipelineContext) -> None:
        self.context = context

    def __call__(self, state: WorkflowState) -> dict[str, Any]:
        created = list(state.get("created_artifacts", []))
        mode = state.get("web_search_mode", "auto")
        sources: list[dict[str, Any]] = []
        if should_research(state.get("user_request", ""), mode):
            try:
                sources = web_search(state.get("user_request", ""), max_results=5)
            except Exception:
                if mode == "on":
                    raise
        for source in sources:
            self.context.evidence.add(
                "WEB_SOURCE",
                source.get("title", "Web source"),
                source.get("url", ""),
                metadata={"query": source.get("query", "")},
            )
        self.context.writer.write_json(
            "research/web_sources.json", {"sources": sources}
        )
        self.context.writer.write_text(
            "research/web_research_summary.ko.md", summarize_web_research(sources, mode)
        )
        created.extend(
            ["research/web_sources.json", "research/web_research_summary.ko.md"]
        )
        return {
            "status": STATUS_RESEARCHING,
            "web_sources_path": str(
                self.context.writer.path("research/web_sources.json")
            ),
            "created_artifacts": created,
        }
