"""언어 계약과 대화 내 보정 한도를 검증한다."""

import json

import httpx2
import pytest

from backend.config import MagiConfig
from backend.errors import MagiError, RequirementNormalizationError
from backend.infrastructure.artifact_writer import ArtifactWriter
from backend.infrastructure.output_language import language_issues
from backend.infrastructure.provider_call import complete_with_usage
from backend.models import InterviewResponse, LockResponse, SpecResponse, ReviewResponse, ReportResponse, InterviewResult, QAItem
from backend.providers.llm_provider import OpenAIProvider
from backend.services.requirement_lock_builder import RequirementLockBuilder
from test_conversation_structured import interview, packet, transport
from prompt_fixtures import short_sources, model_context


def lock_value():
    return dict(request_summary="로컬 메모 앱", workflow_constraints=[], mandatory_requirements=[dict(
        id="REQ-001", text="Store notes on Windows.", source="user_answer:PLATFORM-001",
        original_text="윈도우에 저장해주세요", sources=[])], recommended_requirements=[],
        optional_requirements=[], non_scope=[], constraints=[], assumptions=[],
        acceptance_criteria_seed=["REQ-001: Verify local persistence."], unresolved_questions=[])


def test_field_languages_and_originals():
    value = InterviewResponse.model_validate({**interview(),
        "blocking_questions": [dict(question_id="PLATFORM-001", question="Windows에서 실행하나요?")],
        "assumptions": ["Python을 사용한다고 가정합니다."],
        "pre_answers": [dict(question_id="A-1", question="Original question", answer="Original answer")]})
    assert language_issues(value) == []
    lock = LockResponse.model_validate(lock_value())
    assert language_issues(lock) == []
    assert lock.mandatory_requirements[0].original_text == "윈도우에 저장해주세요"
    lock.request_summary = "Build a local notes application"
    lock.mandatory_requirements[0].text = "메모를 저장한다"
    assert language_issues(lock) == ["request_summary: ko", "mandatory_requirements[0].text: en"]


def test_english_code_original_quote_and_mixed_prose():
    value = SpecResponse.model_validate({key: "English implementation prose." for key in SpecResponse.model_fields if key not in {"decisions", "spec_links"}})
    value.input_contract = 'Accept text.\n```python\nprint("한글 코드")\n```\n`한글 식별자`\n<original_quote>원문 인용</original_quote>\n> 사용자 인용'
    assert language_issues(value) == []
    value.mission = "English sentence와 한글 설명이 섞였습니다."
    assert language_issues(value) == ["mission: en"]


def test_review_explanations_and_evidence():
    value = ReviewResponse.model_validate({"issues": [dict(defect_kind='spec_omission', resolution_reason='확정 요구사항에 따라 명세를 보완해야 합니다.', missing_information='', decision_key="AC-001", section="## 1. Mission", severity="major",
        checklist_id="AC-001", problem="완료 조건이 없습니다.", required_change='완료 조건에 "Verify local persistence."를 추가하세요.',
        requirement_id="REQ-001", evidence=[dict(source="draft", quote="Original English excerpt")])]})
    assert language_issues(value) == []
    value.issues[0].problem = "The completion criteria are missing"
    assert language_issues(value) == ["issues[0].problem: ko"]
    assert value.issues[0].evidence[0].quote == "Original English excerpt"


def test_report_technical_only_and_empty_fields():
    value = ReportResponse(summary="검토가 차단되었습니다.", blocking_causes=["HTTP 404", "`REQ-001`"],
        required_user_decisions=[], resume_conditions=["사용자 결정을 확정해주세요."])
    assert language_issues(value) == []
    value.summary = ""
    assert language_issues(value) == ["summary: ko"]


@pytest.mark.parametrize("succeeds", [True, False])
def test_language_repair_three_times_in_same_conversation(tmp_path, succeeds):
    requests = []
    wrong = {**interview(), "assumptions": ["Assume a local application"]}
    correct = {**interview(), "assumptions": ["로컬 앱으로 가정합니다."]}

    def handle(request):
        requests.append(json.loads(request.content))
        value = correct if succeeds and len(requests) == 2 else wrong
        return httpx2.Response(200, json=packet(value, f"resp_{len(requests)}"))

    writer = ArtifactWriter(tmp_path)
    with transport(handle):
        if succeeds:
            result = complete_with_usage(writer, OpenAIProvider(api_key="fake-test-value"),
                [{"role": "system", "content": "Interview"}, {"role": "user", "content": "Request"}],
                model="gpt-6-luna", stage="interview")
            assert result.assumptions == correct["assumptions"]
        else:
            with pytest.raises(MagiError, match="language"):
                complete_with_usage(writer, OpenAIProvider(api_key="fake-test-value"),
                    [{"role": "system", "content": "Interview"}], model="gpt-6-luna", stage="interview")
    assert len(requests) == (2 if succeeds else 4)
    assert requests[0]["conversation"] == requests[1]["conversation"]
    assert all(item["role"] != "assistant" for body in requests for item in body["input"])
    assert "assumptions[0]: ko" in json.dumps(requests[1]["input"])
    assert "Assume a local application" not in json.dumps(requests[1]["input"])


@pytest.mark.parametrize("order", ["language_then_source", "source_then_language"])
def test_lock_semantic_and_language_share_three_repairs(tmp_path, order):
    calls = []
    latest = {}
    def handle(request):
        calls.append(json.loads(request.content))
        model_context(calls[-1]['input'], latest)
        value = lock_value()
        if len(calls) == 1:
            if order == "source_then_language":
                value["mandatory_requirements"][0]["source"] = "user_request"
            else:
                value["request_summary"] = "Build a notes application"
        elif order == "language_then_source":
            value["mandatory_requirements"][0]["source"] = "user_request"
        elif order == "source_then_language":
            value["request_summary"] = "Build a notes application"
        return httpx2.Response(200, json=packet(short_sources(value, latest), f"resp_{len(calls)}"))

    writer = ArtifactWriter(tmp_path)
    provider = OpenAIProvider(api_key="fake-test-value")
    def complete(messages):
        return complete_with_usage(writer, provider, messages, model="gpt-6-luna", stage="requirement_lock")
    def build():
        return RequirementLockBuilder().build({'user_request': '메모 앱', 'confirmed_user_sources': {'user_answer:PLATFORM-001': 'Windows'}}, {}, InterviewResult("feature", [], [],
            pre_answers=[QAItem("PLATFORM-001", "대상 플랫폼?", "Windows")]), provider_messages_fn=complete)
    with transport(handle):
        with pytest.raises(RequirementNormalizationError):
            build()
    assert len(calls) == 4
    assert calls[0]["conversation"] == calls[1]["conversation"]


@pytest.mark.parametrize("language", [{"analysis": "en"}, {"final_spec": "ko"}])
def test_unsupported_language_config_rejected(language):
    with pytest.raises(MagiError):
        MagiConfig.from_dict({"language": language})
