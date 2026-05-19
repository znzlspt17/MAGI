from __future__ import annotations

from pathlib import Path

import pytest

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
    assert heartbeat["interval_seconds"] == 10.0
    assert "last_heartbeat_at" in heartbeat
    assert "state/heartbeat.json" in state["created_artifacts"]


def test_guarded_command_result_logged_when_allowed(mock_engine, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine.generate_from_text(
        text="Run guarded command diagnostics.",
        output_dir=str(output),
        web_search_mode="off",
        allow_command_execution=True,
    )

    state = read_json(output / "state" / "magi_state.json")
    command_log = read_json(output / "execution" / "command_log.json")
    evidence = read_json(output / "evidence" / "evidence_registry.json")

    assert state["command_execution_allowed"] is True
    assert len(command_log["commands"]) >= 1
    assert command_log["commands"][0]["command"] == ["pytest", "--version"]
    assert "timestamp" in command_log["commands"][0]
    assert any(item["evidence_type"] == "COMMAND_RESULT" for item in evidence["items"])


def test_no_guarded_command_results_when_not_allowed(mock_engine, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine.generate_from_text(
        text="Do not run guarded commands.",
        output_dir=str(output),
        web_search_mode="off",
        allow_command_execution=False,
    )

    command_log = read_json(output / "execution" / "command_log.json")
    evidence = read_json(output / "evidence" / "evidence_registry.json")

    assert command_log["commands"] == []
    assert not any(item["evidence_type"] == "COMMAND_RESULT" for item in evidence["items"])


def test_guarded_command_fallback_includes_timestamp(
    monkeypatch: pytest.MonkeyPatch,
    mock_engine,
    tmp_path: Path,
) -> None:
    output = tmp_path / "out"

    def raise_exec(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("simulated command failure")

    monkeypatch.setattr("magi_spec.graph.nodes.execute_command_guarded", raise_exec)

    mock_engine.generate_from_text(
        text="Run guarded command diagnostics.",
        output_dir=str(output),
        web_search_mode="off",
        allow_command_execution=True,
    )

    command_log = read_json(output / "execution" / "command_log.json")
    entry = command_log["commands"][0]
    assert entry["exit_code"] == -1
    assert "timestamp" in entry
    assert entry["stderr_summary"] == "simulated command failure"
