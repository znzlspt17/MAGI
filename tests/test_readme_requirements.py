from __future__ import annotations

from pathlib import Path


def test_readme_covers_v1_contract_topics() -> None:
    readme = Path("README.md").read_text(encoding="utf-8").lower()
    required_fragments = [
        "magi spec engine is a local python package",
        "does not",
        "installation",
        "environment setup",
        "openai-only",
        "future provider",
        "model-blind",
        "cli usage",
        "python api",
        "project folder context",
        "web research",
        "command execution guard",
        "output directory",
        "approve the reviewed candidate",
        "review loop",
        "critical report",
    ]
    for fragment in required_fragments:
        assert fragment in readme


def test_readme_states_magi_does_not_implement_target_project() -> None:
    readme = Path("README.md").read_text(encoding="utf-8").lower()
    assert "does not implement the requested target project" in readme
