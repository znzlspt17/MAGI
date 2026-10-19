"""요청 인터뷰 단계."""

from __future__ import annotations
from typing import Any
from backend.models import STATUS_ANALYZING
from backend.infrastructure.provider_call import complete_with_usage
from backend.models import InterviewResponse
from backend.models import WorkflowState
from backend.pipeline.context import PipelineContext


class InterviewStage:
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
        route = self.context.config.model_routing[self.context.interviewer.agent_id]
        provider = self.context.provider

        def complete(messages: list[dict[str, str]]) -> InterviewResponse:
            return complete_with_usage(
                self.context.writer,
                provider,
                messages,
                model=route.model,
                stage="interview",
                temperature=0,
            )

        result = self.context.interviewer.run(
            state, manifest, provider_messages_fn=complete
        )
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
            self.context.writer.write_text(path, content, overwrite=True)
            if path not in created:
                created.append(path)
        for assumption in result.assumptions:
            self.context.evidence.add("AGENT_ASSUMPTION", assumption, "interview")
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
