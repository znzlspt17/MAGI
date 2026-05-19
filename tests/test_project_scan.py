from __future__ import annotations

from pathlib import Path

import pytest

from magi_spec.skills.project_scan import read_project_file, scan_project_folder


def test_read_project_file_rejects_path_escape(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("ok", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes project root"):
        read_project_file(project, "../outside.txt")


def test_read_project_file_rejects_secret_like_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "api_token.txt").write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError, match="ignored or secret-like file"):
        read_project_file(project, "api_token.txt")


def test_scan_project_folder_ignores_env_file(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text("A=1", encoding="utf-8")
    (project / "README.md").write_text("# ok", encoding="utf-8")

    manifest = scan_project_folder(project)
    paths = [item["path"] for item in manifest["files"]]

    assert "README.md" in paths
    assert ".env" not in paths
