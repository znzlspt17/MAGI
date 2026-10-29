"""실제 모델을 호출하지 않는 명세 작성용 구조화 응답."""

import json
from backend.models import (
    CompletionResult,
    InterviewResponse,
    LockResponse,
    ReviewResponse,
    ReviewResolutionResponse,
    SpecDraftResponse as SpecResponse,
)


def resolution_value(issues):
    issues = [
        {"resolution_kind": "auto_fix", "decision_question": None, **item}
        for item in issues
    ]
    return {
        "resolutions": [
            dict(
                issue_id=item["issue_id"],
                defect_kind="requirements_gap"
                if item["resolution_kind"] == "user_decision"
                else "spec_omission",
                resolution_kind=item["resolution_kind"],
                resolution_reason="확정 근거와 누락 정보를 대조했습니다.",
                missing_information="사용자 동작을 결정할 정보가 없습니다."
                if item["resolution_kind"] == "user_decision"
                else "",
                decision_key=item["decision_key"],
                decision_question=item["decision_question"],
                required_change=item["required_change"],
                basis_refs=[item["requirement_id"] or "user_request"],
                impact="behavior"
                if item["resolution_kind"] == "user_decision"
                else "none",
                conflicting_source=None,
            )
            for item in issues
        ]
    }


class DecisionProvider:
    provider_name = "openai"

    def __init__(self, reviews):
        self.reviews = iter(reviews)
        self.calls = []
        self.contexts = {}

    def validate_credentials(self):
        pass

    def create_conversation(self):
        from uuid import uuid4
        return "conv_" + uuid4().hex

    def initialize_conversation(self, conversation_id, messages):
        pass

    def complete_result(self, messages, **kwargs):
        schema = kwargs["text_format"]
        from backend.pipeline.planner import PlannerDecision

        if schema is PlannerDecision:
            from prompt_fixtures import planner_result

            return planner_result(messages)
        self.calls.append(schema)
        for message in messages:
            if message["content"].startswith("Canonical context:\n"):
                self.contexts[schema] = json.loads(message["content"].split("\n", 1)[1])
        if schema is InterviewResponse:
            parsed = schema(
                request_type="feature",
                assumptions=[],
                blocking_questions=[],
                additional_questions=[],
                pre_answers=[
                    dict(
                        question_id="PLATFORM-001",
                        question="대상 플랫폼은 무엇인가요?",
                        answer="Windows",
                    )
                ],
            )
        elif schema is LockResponse:
            answers = self.contexts[schema]["saved_answers"]
            sources = self.contexts[schema]["sources"]
            answers = [
                {**item, "answer": sources[item["answer_source"]].get("text", "")}
                if "answer_source" in item
                else item
                for item in answers
            ]
            text = "Store notes locally."
            if any(a["answer"] == "30일" for a in answers):
                text += " Retain notes for 30 days."
            parsed = schema(
                request_summary="로컬 메모 앱",
                workflow_constraints=[],
                mandatory_requirements=[
                    dict(
                        id="REQ-001",
                        text=text,
                        source=next(
                            key
                            for key, item in sources.items()
                            if item["type"] == "user_request"
                        ),
                        original_text="메모를 저장해주세요",
                        sources=[
                            key
                            for key, item in sources.items()
                            if item["type"] == "user_answer"
                            and any(
                                a["question_id"] == item["question_id"] for a in answers
                            )
                        ],
                    )
                ],
                recommended_requirements=[],
                optional_requirements=[],
                non_scope=[],
                constraints=[],
                assumptions=[],
                acceptance_criteria_seed=["REQ-001: Verify local persistence."],
                unresolved_questions=[],
            )
        elif schema is SpecResponse:
            from task_fixture import with_tasks

            parsed = schema(
                **with_tasks(
                    {
                        key: [
                            dict(
                                item_id="ITEM-" + key,
                                text="Store notes locally. Verify local persistence on Windows.",
                                requirement_ids=["REQ-001"]
                                if key == "architecture"
                                else [],
                                decision_ids=[],
                            )
                        ]
                        for key in schema.model_fields
                        if key != "decisions"
                    }
                )
            )
        elif schema is ReviewResponse:
            parsed = schema(issues=next(self.reviews))
            self.last_issues = parsed.issues
        elif schema is ReviewResolutionResponse:
            issues = [
                {
                    **item,
                    **{
                        key: getattr(previous, key)
                        for key in ("resolution_kind", "decision_question")
                    },
                }
                for item in self.contexts[schema]["issues"]
                for previous in self.last_issues
                if previous.checklist_id == item["checklist_id"]
            ]
            parsed = schema.model_validate(resolution_value(issues))
        else:
            raise AssertionError("Unsupported model stage: " + schema.__name__)
        if schema is LockResponse:
            for ref, item in self.contexts[schema].get("sources", {}).items():
                if "user_feedback" in item.get("roles", [item["type"]]):
                    parsed.mandatory_requirements[0].sources.append(ref)
        return CompletionResult(
            text="", parsed=parsed, response_id=f"resp_review{len(self.calls)}"
        )
