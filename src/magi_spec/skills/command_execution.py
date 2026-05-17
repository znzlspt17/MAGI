"""Guarded command execution skill."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from magi_spec.core.errors import CommandExecutionError
from magi_spec.skills.permissions import COMMAND_CAPABLE_AGENTS


ALLOWED_PREFIXES = [
    ("pytest",),
    ("ruff", "check"),
    ("mypy",),
    ("python", "-m", "build"),
    ("python", "-m", "pip", "show"),
    ("python", "-m", "pip", "list"),
]

FORBIDDEN_TOKENS = {
    "rm",
    "del",
    "erase",
    "rmdir",
    "remove-item",
    "move-item",
    "git",
    "curl",
    "wget",
    "scp",
    "ssh",
    "deploy",
}


def _is_allowed(command: list[str]) -> bool:
    lowered = [part.lower() for part in command]
    if any(token in FORBIDDEN_TOKENS for token in lowered):
        return False
    return any(tuple(lowered[: len(prefix)]) == prefix for prefix in ALLOWED_PREFIXES)


def execute_command_guarded(
    command: list[str],
    *,
    working_directory: str | Path,
    requesting_agent: str,
    allowed: bool,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    if not allowed:
        raise CommandExecutionError(
            "Command execution was requested but --allow-command-execution is not enabled."
        )
    if requesting_agent not in COMMAND_CAPABLE_AGENTS:
        raise CommandExecutionError(
            f"Agent '{requesting_agent}' is not allowed to execute guarded commands."
        )
    if not command or not _is_allowed(command):
        raise CommandExecutionError(f"Command is not allowed by MAGI policy: {command}")

    completed = subprocess.run(
        command,
        cwd=Path(working_directory),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    return {
        "command": command,
        "working_directory": str(Path(working_directory).resolve()),
        "exit_code": completed.returncode,
        "stdout_summary": completed.stdout[-4000:],
        "stderr_summary": completed.stderr[-4000:],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "requesting_agent": requesting_agent,
    }
