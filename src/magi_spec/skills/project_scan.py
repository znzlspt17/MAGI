"""Read-only project folder scanner."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any


IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
}
IGNORED_NAMES = {".env", ".env.local", ".envrc"}
SECRET_MARKERS = {"secret", "token", "credential", "password", "private_key"}
MAX_FILE_SIZE = 200_000
PREVIEW_SIZE = 4_000


def should_ignore(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    if parts & IGNORED_DIRS:
        return True
    name = path.name.lower()
    if name in IGNORED_NAMES:
        return True
    return any(marker in name for marker in SECRET_MARKERS)


def is_probably_text(path: Path) -> bool:
    mime, _ = mimetypes.guess_type(str(path))
    if mime is None:
        return path.suffix.lower() in {
            ".py",
            ".md",
            ".txt",
            ".toml",
            ".json",
            ".yaml",
            ".yml",
            ".ini",
            ".cfg",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".css",
            ".html",
        }
    return mime.startswith("text/") or mime in {"application/json"}


def scan_project_folder(project_dir: str | Path) -> dict[str, Any]:
    root = Path(project_dir).resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Invalid project directory: {project_dir}")

    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir() or should_ignore(path):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        text_candidate = is_probably_text(path)
        if stat.st_size > MAX_FILE_SIZE and not text_candidate:
            continue
        relative = path.relative_to(root).as_posix()
        entry: dict[str, Any] = {
            "path": relative,
            "size": stat.st_size,
            "text": False,
            "preview": "",
        }
        if stat.st_size <= MAX_FILE_SIZE and text_candidate:
            try:
                entry["preview"] = path.read_text(encoding="utf-8", errors="replace")[:PREVIEW_SIZE]
                entry["text"] = True
            except OSError:
                entry["preview"] = ""
        files.append(entry)

    return {
        "root": str(root),
        "file_count": len(files),
        "files": files,
        "ignored_directories": sorted(IGNORED_DIRS),
        "ignored_secret_patterns": sorted(SECRET_MARKERS),
    }


def summarize_project_context(manifest: dict[str, Any]) -> str:
    text_files = [item for item in manifest.get("files", []) if item.get("text")]
    important = [
        item["path"]
        for item in text_files
        if Path(item["path"]).name.lower()
        in {"readme.md", "pyproject.toml", "package.json", "requirements.txt"}
    ]
    lines = [
        "# 프로젝트 컨텍스트 요약",
        "",
        f"- 프로젝트 루트: `{manifest.get('root', '')}`",
        f"- 스캔된 파일 수: {manifest.get('file_count', 0)}",
        f"- 텍스트로 읽은 파일 수: {len(text_files)}",
    ]
    if important:
        lines.append("- 주요 파일: " + ", ".join(f"`{path}`" for path in important))
    else:
        lines.append("- 주요 메타데이터 파일은 발견되지 않았습니다.")
    lines.append("")
    lines.append("스캔은 읽기 전용으로 수행되었고, 기본 제외 디렉터리와 비밀 파일 패턴은 건너뛰었습니다.")
    return "\n".join(lines) + "\n"


def read_project_file(project_dir: str | Path, relative_path: str) -> str:
    root = Path(project_dir).resolve()
    path = (root / relative_path).resolve()
    if root not in path.parents and path != root:
        raise ValueError(f"Project file path escapes project root: {relative_path}")
    if should_ignore(path):
        raise ValueError(f"Refusing to read ignored or secret-like file: {relative_path}")
    return path.read_text(encoding="utf-8", errors="replace")
