"""필드별 언어 계약 검사. 완전한 자연어 언어 판별기는 아니다."""

import re

from backend.errors import Error
from backend.models import InterviewResponse, LockResponse, ReviewResponse, SpecResponse, SpecDraftResponse, ReportResponse
from backend.models import ReviewResolutionResponse
from backend.models import SpecTranslationResponse
from backend.models import QuestionFormSpec


LANGUAGE_RULES = {
    "spec_translation": "Translate specification headings and prose to Korean. Preserve code, paths, IDs, numerical values and marked original quotations verbatim. Do not add or remove requirements.",
    "interview": "Questions and assumption explanations: Korean. Preserve supplied user answers verbatim. Enums and IDs stay unchanged.",
    "requirement_lock": "request_summary and unresolved_questions: Korean. Requirement text, workflow_constraints text, assumption text and acceptance_criteria_seed: English. Preserve original_text and user answers verbatim; do not translate source markers or IDs.",
    "spec_compile": "All section prose: English. Preserve code, paths, product names and necessary original quotations. Put original-language quotations in <original_quote>...</original_quote> blocks or Markdown blockquotes; code belongs in code spans or fenced blocks.",
    "review_resolution": "resolution_reason, missing_information, decision_question, required_change: Korean. Quote proposed English specification wording verbatim. Keep IDs and basis_refs unchanged.",
    "checklist_critic": "problem, required_change and decision_question explanations: Korean. Proposed sentences to insert into the specification: English, quoted or in code blocks. Preserve evidence.quote and identifiers verbatim.",
    "critical_reporter": "summary, blocking_causes, required_user_decisions and resume_conditions: Korean. Preserve quoted evidence, code, paths and technical identifiers verbatim.",
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

    if isinstance(value, InterviewResponse):
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
                field(f"{name}[{index}].text", item.text, "en")
        for name, language in (("acceptance_criteria_seed", "en"), ("unresolved_questions", "ko")):
            for index, text in enumerate(getattr(value, name)):
                field(f"{name}[{index}]", text, language)
    elif isinstance(value, SpecDraftResponse):
        for name in type(value).model_fields:
            if name != "decisions":
                for index, block in enumerate(getattr(value, name)):
                    field(f"{name}[{index}].text", block.text, "en")
    elif isinstance(value, SpecResponse):
        for name, text in value.model_dump().items():
            if name not in {"decisions", "spec_links"}:
                field(name, text, "en")
    elif isinstance(value, ReviewResolutionResponse):
        for index, item in enumerate(value.resolutions):
            guidance(item.decision_form, f"resolutions[{index}].decision_form")
            for name in ("resolution_reason", "required_change"):
                field(f"resolutions[{index}].{name}", getattr(item, name), "ko")
            for name in ("missing_information", "decision_question"):
                if getattr(item, name):
                    field(f"resolutions[{index}].{name}", getattr(item, name), "ko")
    elif isinstance(value, ReviewResponse):
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
    elif isinstance(value, SpecTranslationResponse):
        field("content", value.content, "ko")
    elif isinstance(value, ReportResponse):
        field("summary", value.summary, "ko")
        for name in ("blocking_causes", "required_user_decisions", "resume_conditions"):
            for index, text in enumerate(getattr(value, name)):
                field(f"{name}[{index}]", text, "ko")
    return checks


