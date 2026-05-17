from __future__ import annotations

from pathlib import Path

from conftest import read_json


def test_revise_records_feedback_and_regenerates(mock_engine, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine.generate_from_text(text="Build original.", output_dir=str(output), web_search_mode="off")
    feedback = tmp_path / "feedback.md"
    feedback.write_text("Tighten the acceptance criteria.", encoding="utf-8")

    result = mock_engine.revise(output_dir=str(output), feedback_path=str(feedback))

    assert result.status == "PASS_PENDING_USER_APPROVAL"
    assert (output / "raw" / "revision_feedback.md").exists()
    state = read_json(output / "state" / "magi_state.json")
    assert state["current_round"] == 3
    assert state["final_agent_spec"] is None
