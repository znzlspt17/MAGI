from __future__ import annotations

import json
from pathlib import Path

from magi_spec.cli import main


def test_cli_generate_from_text(mock_config_file: Path, tmp_path: Path) -> None:
    output = tmp_path / "magi_output"

    code = main(
        [
            "generate",
            "--text",
            "Build a small Python package.",
            "--output",
            str(output),
            "--config",
            str(mock_config_file),
        ]
    )

    assert code == 0
    assert (output / "raw" / "user_request.md").exists()
    assert (output / "draft" / "approval_candidate_spec.en.md").exists()
    assert not (output / "final" / "FINAL_AGENT_SPEC.md").exists()


def test_cli_generate_from_file(mock_config_file: Path, tmp_path: Path) -> None:
    request = tmp_path / "request.md"
    request.write_text("Build a CLI.", encoding="utf-8")
    output = tmp_path / "magi_output"

    code = main(
        [
            "generate",
            "--input",
            str(request),
            "--output",
            str(output),
            "--web-search",
            "off",
            "--config",
            str(mock_config_file),
        ]
    )

    assert code == 0
    assert (output / "analysis" / "01_intent_parse.ko.md").exists()


def test_cli_status(mock_config_file: Path, tmp_path: Path) -> None:
    output = tmp_path / "magi_output"
    assert (
        main(
            [
                "generate",
                "--text",
                "Build a status command.",
                "--output",
                str(output),
                "--config",
                str(mock_config_file),
            ]
        )
        == 0
    )

    code = main(["status", str(output), "--config", str(mock_config_file)])

    assert code == 0


def test_cli_generate_command_log_exists(
    mock_config_file: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "magi_output"

    code = main(
        [
            "generate",
            "--text",
            "Build something.",
            "--output",
            str(output),
            "--config",
            str(mock_config_file),
        ]
    )

    assert code == 0
    command_log = json.loads((output / "execution" / "command_log.json").read_text(encoding="utf-8"))
    # v2 pipeline does not execute guarded commands during spec generation
    assert isinstance(command_log["commands"], list)
