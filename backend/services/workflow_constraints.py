"""사용자 작업 지시의 실제 출처를 확인한다. 제품 요구사항으로 승격하지 않는다."""

import re


def user_sources(state):
    result = {"user_request": [state.get("original_user_request") or state.get("user_request", "")]}
    result["user_feedback"] = [*state.get("revision_history", []), state.get("revision_feedback", "")]
    # 모델이 인터뷰에서 추론한 pre_answers는 사용자 입력의 증거가 아니다.
    for marker, text in state.get("confirmed_user_sources", {}).items():
        result.setdefault(marker, []).append(text)
        # 저장용 원문 해시를 복원해도 작업 지시의 기존 출처 형식과 정확한 인용을 유지한다.
        base = re.sub(r":[0-9a-f]{64}$", "", marker)
        if base != marker:
            result.setdefault(base, []).append(text)
    return result


def validate_workflow(items, sources=None):
    ids = set()
    for index, item in enumerate(items):
        path = f"workflow_constraints[{index}]"
        if not re.fullmatch(r"WF-[A-Za-z0-9_-]+", item.id) or item.id in ids:
            raise ValueError(path + ".id: must be unique and start with WF-.")
        ids.add(item.id)
        if not item.text.strip() or re.search(r"[가-힣]", item.text) or not item.original_text.strip():
            raise ValueError(path + ": English text and an exact original user quotation are required.")
        markers = [item.source, *item.sources]
        if any(not re.fullmatch(r"user_request|user_feedback|user_answer:[A-Za-z0-9_-]+", marker) for marker in markers):
            raise ValueError(path + ".source: must refer to an actual user input, never system policy.")
        if sources is not None and (any(marker not in sources for marker in markers) or not any(
                isinstance(text, str) and item.original_text in text for text in sources.get(item.source, []))):
            raise ValueError(path + ".original_text: must occur verbatim in the cited actual user input.")


def validate_product_boundary(sheet, texts=()):
    """분류 ID와 확정된 작업 문구가 제품 근거로 재유입되는 것을 차단한다."""
    from backend.knowledge.trace import REQUIREMENT_GROUPS
    content = list(texts)
    if not texts:
        content = [text for group in REQUIREMENT_GROUPS for item in getattr(sheet, group)
                   for text in (item.text, item.original_text)]
        content.extend(sheet.acceptance_criteria_seed)
        content.extend(str(item) for item in sheet.decisions)
    normalized = [" ".join(text.split()).casefold() for text in content]
    for text in content:
        if re.search(r"\bWF-[A-Za-z0-9_-]+", text):
            raise ValueError("Product content must not reference workflow IDs.")
    for item in sheet.workflow_constraints:
        for phrase in (item.text, item.original_text):
            if phrase.strip() and any(" ".join(phrase.split()).casefold() in text for text in normalized):
                raise ValueError("Product content must not include a locked workflow instruction.")


def validate_locked_sources(sheet, state):
    from backend.errors import InvalidStateError
    try:
        validate_workflow(sheet.workflow_constraints, user_sources(state))
    except ValueError:
        raise InvalidStateError("Requirement lock contract is invalid. Start a new generation.") from None
    return sheet
