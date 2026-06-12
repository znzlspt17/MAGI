from __future__ import annotations

from pathlib import Path

from conftest import read_json


def test_generate_writes_stopped_heartbeat(mock_engine, tmp_path: Path) -> None:
    output = tmp_path / "out"
    result = mock_engine.generate_from_text(
        text="Build tests.",
        output_dir=str(output),
        web_search_mode="off",
    )

    heartbeat = read_json(output / "state" / "heartbeat.json")
    state = read_json(output / "state" / "magi_state.json")

    assert result.heartbeat_path == str(output / "state" / "heartbeat.json")
    assert heartbeat["run_id"] == state["run_id"]
    assert heartbeat["running"] is False
    assert heartbeat["lifecycle"] == "stopped"
    assert heartbeat["status"] == "PASS_PENDING_USER_APPROVAL"
    assert "last_heartbeat_at" in heartbeat
    assert "state/heartbeat.json" in state["created_artifacts"]


def test_generate_writes_v2_state(mock_engine, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine.generate_from_text(
        text="Build a deterministic spec generator.",
        output_dir=str(output),
        web_search_mode="off",
    )

    state = read_json(output / "state" / "magi_state.json")
    assert state["status"] == "PASS_PENDING_USER_APPROVAL"
    assert "requirement_lock_sheet" in state
    assert "critic_pass_count" in state
    assert (output / "review" / "checklist_issues.json").exists()
