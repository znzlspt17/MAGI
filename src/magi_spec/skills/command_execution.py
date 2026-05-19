"""Guarded command execution skill."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from magi_spec.core.evidence import EvidenceRegistry
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

    try:
        completed = subprocess.run(
            command,
            cwd=Path(working_directory),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CommandExecutionError(f"Guarded command failed to execute: {exc}") from exc
    return {
        "command": command,
        "working_directory": str(Path(working_directory).resolve()),
        "exit_code": completed.returncode,
        "stdout_summary": completed.stdout[-4000:],
        "stderr_summary": completed.stderr[-4000:],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "requesting_agent": requesting_agent,
    }


def append_guarded_command_result(
    command_result: dict[str, Any],
    *,
    command_log_path: str | Path,
    evidence_registry: EvidenceRegistry | None = None,
) -> dict[str, Any]:
    """Append a guarded command result to execution/command_log.json.

    When an evidence registry is provided, the appended log entry is linked to
    a COMMAND_RESULT evidence item.
    """

    log_path = Path(command_log_path).resolve()
    if log_path.name != "command_log.json" or log_path.parent.name != "execution":
        raise CommandExecutionError(
            "Command results can only be appended to execution/command_log.json."
        )

    entry = _normalize_command_log_entry(command_result)
    if "timestamp" not in entry:
        entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    if "recorded_at" not in entry:
        entry["recorded_at"] = datetime.now(timezone.utc).isoformat()

    log_data = _read_command_log(log_path)
    log_data["commands"].append(entry)

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            json.dumps(log_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except OSError as exc:
        raise CommandExecutionError(f"Failed to append command log: {exc}") from exc

    if evidence_registry is not None:
        command = entry.get("command", [])
        command_text = " ".join(str(part) for part in command)
        evidence = evidence_registry.add(
            "COMMAND_RESULT",
            f"Guarded command exited with code {entry.get('exit_code')}: {command_text}",
            str(log_path),
            metadata={
                "command": command,
                "exit_code": entry.get("exit_code"),
                "timestamp": entry.get("timestamp"),
                "requesting_agent": entry.get("requesting_agent"),
                "working_directory": entry.get("working_directory"),
            },
        )
        entry["evidence_id"] = evidence.evidence_id
        log_data["commands"][-1] = entry
        try:
            log_path.write_text(
                json.dumps(log_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        except OSError as exc:
            raise CommandExecutionError(f"Failed to link command evidence: {exc}") from exc

    return entry


def _read_command_log(log_path: Path) -> dict[str, Any]:
    if not log_path.exists():
        return {"commands": []}
    try:
        data = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CommandExecutionError(f"Failed to read command log: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("commands"), list):
        raise CommandExecutionError("Command log must be a JSON object with a commands list.")
    return data


def _normalize_command_log_entry(command_result: dict[str, Any]) -> dict[str, Any]:
    entry = dict(command_result)
    command = entry.get("command")
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise CommandExecutionError("Command log entry requires a string list `command`.")

    try:
        entry["exit_code"] = int(entry.get("exit_code", -1))
    except (TypeError, ValueError) as exc:
        raise CommandExecutionError("Command log entry has invalid `exit_code`.") from exc

    entry["working_directory"] = str(entry.get("working_directory", ""))
    entry["stdout_summary"] = str(entry.get("stdout_summary", ""))
    entry["stderr_summary"] = str(entry.get("stderr_summary", ""))
    entry["requesting_agent"] = str(entry.get("requesting_agent", ""))
    return entry
