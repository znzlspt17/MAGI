from __future__ import annotations

from pathlib import Path

import pytest

from conftest import read_json
from magi_spec.core.evidence import EvidenceRegistry
from magi_spec.core.errors import CommandExecutionError
from magi_spec.skills.command_execution import append_guarded_command_result, execute_command_guarded


def test_command_execution_blocked_without_flag(tmp_path: Path) -> None:
    with pytest.raises(CommandExecutionError):
        execute_command_guarded(
            ["pytest", "--version"],
            working_directory=tmp_path,
            requesting_agent="melchior",
            allowed=False,
        )


def test_balthasar_cannot_execute_commands(tmp_path: Path) -> None:
    with pytest.raises(CommandExecutionError):
        execute_command_guarded(
            ["pytest", "--version"],
            working_directory=tmp_path,
            requesting_agent="balthasar",
            allowed=True,
        )


def test_destructive_command_blocked(tmp_path: Path) -> None:
    with pytest.raises(CommandExecutionError):
        execute_command_guarded(
            ["git", "status"],
            working_directory=tmp_path,
            requesting_agent="melchior",
            allowed=True,
        )


def test_allowed_command_executes_and_returns_record(tmp_path: Path) -> None:
    record = execute_command_guarded(
        ["python", "-m", "pip", "show", "pip"],
        working_directory=tmp_path,
        requesting_agent="melchior",
        allowed=True,
    )

    assert record["command"] == ["python", "-m", "pip", "show", "pip"]
    assert "exit_code" in record
    assert "timestamp" in record
    assert record["requesting_agent"] == "melchior"


def test_append_guarded_command_result_to_command_log(tmp_path: Path) -> None:
    log_path = tmp_path / "execution" / "command_log.json"
    result = {
        "command": ["pytest", "--version"],
        "working_directory": str(tmp_path),
        "exit_code": 0,
        "stdout_summary": "pytest 8.0.0",
        "stderr_summary": "",
        "timestamp": "2026-05-19T00:00:00+00:00",
        "requesting_agent": "melchior",
    }

    entry = append_guarded_command_result(result, command_log_path=log_path)

    assert entry["command"] == ["pytest", "--version"]
    assert entry["timestamp"] == "2026-05-19T00:00:00+00:00"
    assert entry["recorded_at"]
    assert read_json(log_path)["commands"] == [entry]


def test_append_guarded_command_result_can_register_evidence(tmp_path: Path) -> None:
    log_path = tmp_path / "execution" / "command_log.json"
    evidence = EvidenceRegistry()

    entry = append_guarded_command_result(
        {
            "command": ["ruff", "check", "."],
            "working_directory": str(tmp_path),
            "exit_code": 1,
            "stdout_summary": "",
            "stderr_summary": "lint failed",
            "timestamp": "2026-05-19T00:00:00+00:00",
            "requesting_agent": "casper",
        },
        command_log_path=log_path,
        evidence_registry=evidence,
    )

    assert entry["evidence_id"] == evidence.items[0].evidence_id
    assert evidence.items[0].evidence_type == "COMMAND_RESULT"
    assert evidence.items[0].metadata["command"] == ["ruff", "check", "."]
    assert read_json(log_path)["commands"][0]["evidence_id"] == evidence.items[0].evidence_id


def test_append_guarded_command_result_rejects_unexpected_log_path(tmp_path: Path) -> None:
    with pytest.raises(CommandExecutionError):
        append_guarded_command_result(
            {"command": ["pytest"], "exit_code": 0},
            command_log_path=tmp_path / "command_log.json",
        )


def test_append_guarded_command_result_adds_timestamp_if_missing(tmp_path: Path) -> None:
    log_path = tmp_path / "execution" / "command_log.json"
    entry = append_guarded_command_result(
        {
            "command": ["pytest", "--version"],
            "working_directory": str(tmp_path),
            "exit_code": 0,
            "stdout_summary": "",
            "stderr_summary": "",
            "requesting_agent": "melchior",
        },
        command_log_path=log_path,
    )
    assert "timestamp" in entry


def test_append_guarded_command_result_rejects_invalid_command_shape(tmp_path: Path) -> None:
    log_path = tmp_path / "execution" / "command_log.json"
    with pytest.raises(CommandExecutionError, match="string list `command`"):
        append_guarded_command_result(
            {
                "command": "pytest --version",
                "exit_code": 0,
            },
            command_log_path=log_path,
        )


def test_append_guarded_command_result_rejects_invalid_exit_code(tmp_path: Path) -> None:
    log_path = tmp_path / "execution" / "command_log.json"
    with pytest.raises(CommandExecutionError, match="invalid `exit_code`"):
        append_guarded_command_result(
            {
                "command": ["pytest", "--version"],
                "exit_code": "not-a-number",
            },
            command_log_path=log_path,
        )
