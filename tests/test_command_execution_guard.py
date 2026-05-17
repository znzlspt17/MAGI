from __future__ import annotations

from pathlib import Path

import pytest

from magi_spec.core.errors import CommandExecutionError
from magi_spec.skills.command_execution import execute_command_guarded


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
