from __future__ import annotations

from magi_spec.schemas.requirement_lock import (
    AssumptionItem,
    QAItem,
    RequirementItem,
    RequirementLockSheet,
)


def test_roundtrip_to_dict_from_dict() -> None:
    sheet = RequirementLockSheet(
        lock_id="lock_test01",
        request_type="feature",
        request_summary="Build a test feature",
        user_answers=[QAItem("Q-001", "Who is the user?", "Developers")],
        mandatory_requirements=[RequirementItem("REQ-001", "Implement it", "user_request")],
        non_scope=[RequirementItem("NS-001", "Do not deploy", "system")],
        assumptions=[AssumptionItem("ASM-001", "Follow conventions", "low")],
        acceptance_criteria_seed=["Feature works end-to-end"],
        source_refs=["raw/user_request.md"],
    )
    d = sheet.to_dict()
    restored = RequirementLockSheet.from_dict(d)

    assert restored.lock_id == sheet.lock_id
    assert restored.request_type == sheet.request_type
    assert restored.request_summary == sheet.request_summary
    assert len(restored.user_answers) == 1
    assert restored.user_answers[0].question_id == "Q-001"
    assert len(restored.mandatory_requirements) == 1
    assert restored.mandatory_requirements[0].id == "REQ-001"
    assert len(restored.non_scope) == 1
    assert len(restored.assumptions) == 1
    assert restored.assumptions[0].risk == "low"
    assert restored.acceptance_criteria_seed == ["Feature works end-to-end"]


def test_to_markdown_contains_mandatory_and_nonscope() -> None:
    sheet = RequirementLockSheet.build_fallback(
        request_type="feature",
        request_summary="Build something",
    )
    md = sheet.to_markdown()
    assert "필수 요구사항" in md
    assert "비범위" in md
    assert "Out of Scope" in md


def test_fallback_has_non_scope() -> None:
    sheet = RequirementLockSheet.build_fallback()
    assert len(sheet.non_scope) >= 1
    assert any("directly" in r.text.lower() or "implement" in r.text.lower()
               for r in sheet.non_scope)


def test_invalid_request_type_coerced_to_feature() -> None:
    sheet = RequirementLockSheet.from_dict({
        "lock_id": "x",
        "request_type": "garbage",
        "request_summary": "",
    })
    assert sheet.request_type == "feature"


def test_fallback_blocking_questions_become_unresolved() -> None:
    sheet = RequirementLockSheet.build_fallback(
        blocking_questions=["What is the primary user?"]
    )
    assert "What is the primary user?" in sheet.unresolved_questions


def test_from_dict_missing_fields_use_defaults() -> None:
    sheet = RequirementLockSheet.from_dict({"request_type": "bugfix", "request_summary": "Fix bug"})
    assert sheet.request_type == "bugfix"
    assert sheet.mandatory_requirements == []
    assert sheet.non_scope == []
    assert sheet.assumptions == []


def test_to_markdown_shows_acceptance_criteria_seed() -> None:
    sheet = RequirementLockSheet(
        lock_id="l",
        request_type="feature",
        request_summary="s",
        acceptance_criteria_seed=["All tests pass", "No regressions"],
    )
    md = sheet.to_markdown()
    assert "All tests pass" in md
    assert "No regressions" in md


def test_state_roundtrip_preserves_fields() -> None:
    """Ensure MagiState fields can round-trip through to_dict/from_dict."""
    from magi_spec.core.state import MagiState
    state = MagiState(
        run_id="r1",
        status="DRAFT",
        user_request="req",
        input_source="direct_text",
        project_dir=None,
        output_dir="/tmp",
        requirement_lock_sheet={"lock_id": "l", "request_type": "feature", "request_summary": "s"},
        structured_issues=[{"issue_id": "A"}],
        critic_pass_count=1,
        max_critic_passes=2,
    )
    d = state.to_dict()
    restored = MagiState.from_dict(d)
    assert restored.requirement_lock_sheet is not None
    assert restored.critic_pass_count == 1
    assert restored.max_critic_passes == 2


def test_state_from_dict_minimal_state_uses_defaults() -> None:
    """Loading a minimal state dict should apply defaults."""
    from magi_spec.core.state import MagiState
    minimal = {
        "run_id": "r1",
        "status": "DRAFT",
        "user_request": "req",
        "input_source": "direct_text",
        "project_dir": None,
        "output_dir": "/tmp",
    }
    state = MagiState.from_dict(minimal)
    assert state.requirement_lock_sheet is None
    assert state.structured_issues == []
    assert state.critic_pass_count == 0
