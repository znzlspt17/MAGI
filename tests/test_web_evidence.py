from __future__ import annotations

from pathlib import Path

from conftest import read_json


def test_web_artifacts_saved_when_search_off(mock_engine, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine.generate_from_text(text="Build without web.", output_dir=str(output), web_search_mode="off")

    sources = read_json(output / "research" / "web_sources.json")
    assert sources == {"sources": []}
    assert (output / "research" / "web_research_summary.ko.md").exists()
