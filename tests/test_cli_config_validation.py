from __future__ import annotations

from pathlib import Path

from magi_spec.cli import main


def test_cli_generate_fails_with_invalid_config(tmp_path: Path) -> None:
    config_path = tmp_path / "bad_config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "model_routing:",
                "  melchior:",
                "    provider: mock",
                "    model: deterministic",
                "  balthasar:",
                "    provider: mock",
                "    model: deterministic",
                "  casper:",
                "    provider: mock",
                "    model: deterministic",
                "  conflict_resolver:",
                "    provider: mock",
                "    model: deterministic",
                "  spec_composer:",
                "    provider: mock",
                "    model: deterministic",
                "  critical_reporter:",
                "    provider: mock",
                "    model: deterministic",
                "review:",
                "  min_review_rounds: 5",
                "  max_review_rounds: 3",
            ]
        ),
        encoding="utf-8",
    )

    code = main(
        [
            "generate",
            "--text",
            "Build package.",
            "--output",
            str(tmp_path / "out"),
            "--config",
            str(config_path),
        ]
    )

    assert code == 1
