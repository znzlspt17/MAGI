from __future__ import annotations

from pathlib import Path

from conftest import read_json


def test_v2_feedback_reflection_preserved_in_lock_sheet(mock_engine_v2, tmp_path: Path) -> None:
    """v2 revise: feedback is reflected in user_answers or constraints, not a full loop reset."""
    output = tmp_path / "out"
    mock_engine_v2.generate_from_text(
        text="Build a report generator.",
        output_dir=str(output),
        web_search_mode="off",
    )
    feedback = tmp_path / "feedback.md"
    feedback.write_text("Add pagination support to the report output.", encoding="utf-8")

    result = mock_engine_v2.revise(output_dir=str(output), feedback_path=str(feedback))
    assert result.status == "PASS_PENDING_USER_APPROVAL"
    assert (output / "raw" / "revision_feedback.md").exists()

    state = read_json(output / "state" / "magi_state.json")
    assert state.get("final_agent_spec") is None


def test_v2_revise_keeps_draft_english_only(mock_engine_v2, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine_v2.generate_from_text(text="Build a tool.", output_dir=str(output), web_search_mode="off")
    feedback = tmp_path / "fb.md"
    feedback.write_text("더 구체적인 완료 기준이 필요합니다.", encoding="utf-8")
    mock_engine_v2.revise(output_dir=str(output), feedback_path=str(feedback))
    spec = (output / "draft" / "approval_candidate_spec.en.md").read_text(encoding="utf-8")
    assert not any("\uac00" <= ch <= "\ud7a3" for ch in spec)
