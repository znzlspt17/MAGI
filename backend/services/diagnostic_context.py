"""검증 실패에서 공개 가능한 참조와 개수만 보존한다."""
from typing import Any


def safe_review_context(source):
    # 2026-11-05: 모델 자유 응답 대신 제한된 ID·기존 섹션·정수만 공개한다.
    import re
    from backend.services.rubric import SECTIONS

    if not isinstance(source, dict):
        return {}
    result: dict[str, Any] = {}
    for key in ("rubric_id", "requirement_id"):
        value = source.get(key)
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value):
            result[key] = value
    for key in ("expected_count", "actual_count"):
        value = source.get(key)
        if type(value) is int and 0 <= value <= 100000:
            result[key] = value
    sections = source.get("allowed_sections")
    if isinstance(sections, list) and all(isinstance(x, str) and x in SECTIONS for x in sections):
        result["allowed_sections"] = sections
    return result
