from __future__ import annotations

from pathlib import Path

from conftest import read_json


def test_generate_with_project_folder(mock_engine, tmp_path: Path) -> None:
    project = tmp_path / "target"
    project.mkdir()
    (project / "README.md").write_text("# Target\n", encoding="utf-8")
    (project / ".env").write_text("SECRET=value\n", encoding="utf-8")
    output = tmp_path / "out"

    result = mock_engine.generate_from_text(
        text="Use the project context.",
        output_dir=str(output),
        project_dir=str(project),
        web_search_mode="off",
    )

    assert result.status == "PASS_PENDING_USER_APPROVAL"
    manifest = read_json(output / "context" / "project_manifest.json")
    assert manifest["file_count"] == 1
    assert manifest["files"][0]["path"] == "README.md"
