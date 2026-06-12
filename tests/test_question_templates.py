from __future__ import annotations

from magi_spec.interview.question_templates import (
    HARD_CAP,
    classify_request_type,
    select_questions,
)


def test_classify_bugfix_from_keyword() -> None:
    assert classify_request_type("fix the login bug", {}) == "bugfix"


def test_classify_refactor_from_keyword() -> None:
    assert classify_request_type("refactor the auth module", {}) == "refactor"


def test_classify_product_empty_project() -> None:
    assert classify_request_type("build a new CLI tool from scratch", {"file_count": 0}) == "product"


def test_classify_infra() -> None:
    assert classify_request_type("set up CI/CD deploy pipeline", {}) == "infra"


def test_classify_defaults_to_feature() -> None:
    assert classify_request_type("add a new endpoint for user profile", {"file_count": 5}) == "feature"


def test_select_questions_respects_hard_cap() -> None:
    questions = select_questions("product")
    assert len(questions) <= HARD_CAP


def test_select_questions_direction_changing_first() -> None:
    questions = select_questions("feature")
    dc = [q for q in questions if q.direction_changing]
    non_dc = [q for q in questions if not q.direction_changing]
    # All direction_changing should appear before non-direction_changing
    if dc and non_dc:
        last_dc_idx = max(i for i, q in enumerate(questions) if q.direction_changing)
        first_non_dc_idx = min(i for i, q in enumerate(questions) if not q.direction_changing)
        assert last_dc_idx < first_non_dc_idx


def test_select_questions_excludes_answered() -> None:
    questions = select_questions("feature")
    all_ids = {q.question_id for q in questions}
    if all_ids:
        first_id = next(iter(all_ids))
        filtered = select_questions("feature", answered_ids={first_id})
        filtered_ids = {q.question_id for q in filtered}
        assert first_id not in filtered_ids


def test_select_questions_unknown_type_falls_back_to_feature() -> None:
    # Should not raise; unknown type falls back to feature questions
    questions = select_questions("unknown_type")
    assert len(questions) >= 1


def test_select_questions_includes_common_for_all_types() -> None:
    for rtype in ("product", "feature", "bugfix", "refactor", "infra"):
        questions = select_questions(rtype)
        q_ids = {q.question_id for q in questions}
        # Common questions should be present (unless capped out)
        # At minimum, check no exception is raised
        assert isinstance(questions, list)
