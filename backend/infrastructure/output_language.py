"""필드별 언어 계약 검사. 완전한 자연어 언어 판별기는 아니다."""

import re

from backend.errors import Error
from backend.models import InterviewResponse, LockResponse, ReviewResponse, SpecResponse, SpecDraftResponse
from backend.models import ReviewResolutionResponse
from backend.models import QuestionFormSpec
from backend.models import RubricResponse


_QUESTION_LANGUAGE = " 질문, 선택지, 영향, 가정과 추천 설명은 한국어로 작성하고 제품명과 OS 이름은 보존하세요."

LANGUAGE_RULES = {
    "rubric_generate": "평가 조건은 한국어로 작성하고 근거 인용과 식별자는 그대로 보존하세요.",
    "interview": "사용자 답변, enum과 ID를 그대로 보존하세요." + _QUESTION_LANGUAGE,
    "requirement_lock": "요구사항, 제약, 가정, 수용 기준과 질문은 한국어로 작성하세요. original_text, 사용자 답변, 출처와 ID는 그대로 보존하세요.",
    "spec_compile": "모든 섹션 본문을 한국어로 작성하고 코드, 경로, 제품명과 원문 인용을 보존하세요. 원문 인용은 <original_quote> 또는 Markdown 인용 블록으로 표시하세요.",
    "review_resolution": "이유, 누락 정보와 수정 내용은 한국어로 작성하세요. ID와 basis_refs는 그대로 유지하세요." + _QUESTION_LANGUAGE,
    "checklist_critic": "검토 문제, 수정 내용, 이유, 지시와 제안 문장은 한국어로 작성하세요. evidence.quote와 식별자는 보존하세요." + _QUESTION_LANGUAGE,
}


class OutputLanguageError(Error):
    def __init__(self, details):
        super().__init__("Output language validation failed.")
        self.validation_details = details


def prose(text):
    text = re.sub(r"(?ms)^ {0,3}(`{3,}|~{3,})[^\n]*\n.*?^ {0,3}\1[^\n]*(?:\n|$)", "", text)
    text = re.sub(r"<original_quote>.*?</original_quote>", "", text, flags=re.S)
    text = re.sub(r"(?m)^\s*>.*$", "", text)
    return re.sub(r"`[^`\n]+`", "", text)


def has_hangul(text):
    return re.search(r"[가-힣ㄱ-ㅎㅏ-ㅣ]", text) is not None


def technical_only(text):
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_./:#-]*", text)
    known = {"Python", "Windows", "Linux", "macOS", "JavaScript", "TypeScript", "JSON", "Markdown", "OpenAI", "Responses", "API", "Pydantic", "HTTP", "SQL"}
    return bool(tokens) and all(token in known or re.fullmatch(r"[A-Z][A-Z0-9_]*", token)
                               or re.search(r"[a-z][A-Z]|[_./:#-]", token) for token in tokens)


def language_issues(value):
    checks = []

    def field(path, text, language):
        body = prose(text).strip()
        if language == "en":
            if has_hangul(body):
                checks.append(f"{path}: en")
        elif not text.strip() or (body and not has_hangul(body) and not technical_only(body)):
            checks.append(f"{path}: ko")

    def guidance(form, path):
        if form is None:
            return
        for index, option in enumerate(form.options):
            if option.impact is not None:
                field(f"{path}.options[{index}].impact", option.impact, "ko")
            for n, text in enumerate(option.assumptions):
                field(f"{path}.options[{index}].assumptions[{n}]", text, "ko")
        if form.recommendation is not None:
            field(f"{path}.recommendation.reason", form.recommendation.reason, "ko")
            for n, text in enumerate(form.recommendation.assumptions):
                field(f"{path}.recommendation.assumptions[{n}]", text, "ko")

    if isinstance(value, RubricResponse):
        for index, rubric_item in enumerate(value.items):
            field(f"items[{index}].condition", rubric_item.condition, "ko")
    elif isinstance(value, InterviewResponse):
        for name in ("blocking_questions", "additional_questions"):
            for index, item in enumerate(getattr(value, name)):
                field(f"{name}[{index}].question", item.question, "ko")
                guidance(item, f"{name}[{index}]")
        for index, text in enumerate(value.assumptions):
            field(f"assumptions[{index}]", text, "ko")
    elif isinstance(value, LockResponse):
        field("request_summary", value.request_summary, "ko")
        for name in ("mandatory_requirements", "recommended_requirements", "optional_requirements", "non_scope", "constraints", "workflow_constraints", "assumptions"):
            for index, item in enumerate(getattr(value, name)):
                field(f"{name}[{index}].text", item.text, "ko")
        for name, language in (("acceptance_criteria_seed", "ko"), ("unresolved_questions", "ko")):
            for index, text in enumerate(getattr(value, name)):
                field(f"{name}[{index}]", text, language)
    elif isinstance(value, SpecDraftResponse):
        for name in type(value).model_fields:
            if name not in {"decisions", "out_of_scope"}:
                for index, block in enumerate(getattr(value, name)):
                    field(f"{name}[{index}].text", block.text, "ko")
                    if name == "implementation_order":
                        field(f"{name}[{index}].title", block.title, "ko")
    elif isinstance(value, SpecResponse):
        for name, text in value.model_dump().items():
            if name not in {"decisions", "spec_links"}:
                field(name, text, "ko")
    elif isinstance(value, ReviewResolutionResponse):
        for index, item in enumerate(value.resolutions):
            guidance(item.decision_form, f"resolutions[{index}].decision_form")
            for name in ("resolution_reason", "required_change"):
                field(f"resolutions[{index}].{name}", getattr(item, name), "ko")
            for name in ("missing_information", "decision_question"):
                if getattr(item, name):
                    field(f"resolutions[{index}].{name}", getattr(item, name), "ko")
    elif isinstance(value, ReviewResponse):
        field("score_reason", value.score_reason, "ko")
        for index, directive in enumerate(value.revision_directives):
            field(f"revision_directives[{index}]", directive, "ko")
        for index, verdict in enumerate(value.rubric_verdicts):
            field(f"rubric_verdicts[{index}].reason", verdict.reason, "ko")
        for index, item in enumerate(value.issues):
            guidance(item.decision_form, f"issues[{index}].decision_form")
            field(f"issues[{index}].resolution_reason", item.resolution_reason, "ko")
            if item.missing_information:
                field(f"issues[{index}].missing_information", item.missing_information, "ko")
            field(f"issues[{index}].problem", item.problem, "ko")
            field(f"issues[{index}].required_change", item.required_change, "ko")
            if item.decision_question is not None:
                field(f"issues[{index}].decision_question", item.decision_question, "ko")
    elif isinstance(value, QuestionFormSpec):
        guidance(value, "form")
    return checks


