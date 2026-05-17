from __future__ import annotations

from pathlib import Path

from conftest import read_json


def test_review_runs_minimum_three_rounds(mock_engine, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine.generate_from_text(
        text="Build a deterministic spec generator.",
        output_dir=str(output),
        web_search_mode="off",
    )

    state = read_json(output / "state" / "magi_state.json")
    assert state["status"] == "PASS_PENDING_USER_APPROVAL"
    assert state["current_round"] == 3
    assert (output / "review_rounds" / "round_01" / "section_status.json").exists()
    assert (output / "review_rounds" / "round_02" / "section_status.json").exists()
    assert (output / "review_rounds" / "round_03" / "section_status.json").exists()


def test_section_status_persisted(mock_engine, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine.generate_from_text(text="Build tests.", output_dir=str(output), web_search_mode="off")
    section_status = read_json(output / "review_rounds" / "round_03" / "section_status.json")

    assert section_status["mission"] == "PASS"
    assert section_status["architecture"] == "PASS"
