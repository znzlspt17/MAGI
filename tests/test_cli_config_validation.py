from __future__ import annotations

from pathlib import Path

from magi_spec.cli import main


def _mock_config(tmp_path: Path, extra_lines: list[str]) -> Path:
    path = tmp_path / "config.yaml"
    base = [
        "model_routing:",
        "  interviewer:",
        "    provider: mock",
        "    model: deterministic",
        "  critic:",
        "    provider: mock",
        "    model: deterministic",
        "  compiler:",
        "    provider: mock",
        "    model: deterministic",
        "  critical_reporter:",
        "    provider: mock",
        "    model: deterministic",
    ]
    path.write_text("\n".join(base + extra_lines), encoding="utf-8")
    return path


def test_cli_generate_fails_with_invalid_web_search(tmp_path: Path) -> None:
    config_path = _mock_config(tmp_path, ["capabilities:", "  web_search: sometimes"])

    code = main([
        "generate", "--text", "Build package.",
        "--output", str(tmp_path / "out"),
        "--config", str(config_path),
    ])

    assert code == 1


def test_cli_generate_fails_with_invalid_max_critic_passes(tmp_path: Path) -> None:
    config_path = _mock_config(tmp_path, ["review:", "  max_critic_passes: 10"])

    code = main([
        "generate", "--text", "Build package.",
        "--output", str(tmp_path / "out"),
        "--config", str(config_path),
    ])

    assert code == 1
