"""Artifact persistence helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from magi_spec.core.errors import ArtifactError


REQUIRED_DIRECTORIES = [
    "raw",
    "context",
    "research",
    "evidence",
    "execution",
    "analysis",
    "agents/initial",
    "review_rounds",
    "draft",
    "final",
    "critical",
    "state",
]


class ArtifactWriter:
    """Writes UTF-8 artifacts under one run output directory."""

    def __init__(self, output_dir: str | Path, *, allow_overwrite: bool = False) -> None:
        self.output_dir = Path(output_dir).resolve()
        self.allow_overwrite = allow_overwrite

    def prepare(self) -> None:
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            for directory in REQUIRED_DIRECTORIES:
                (self.output_dir / directory).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ArtifactError(f"Failed to prepare output directory: {exc}") from exc

    def path(self, relative_path: str | Path) -> Path:
        path = (self.output_dir / relative_path).resolve()
        if self.output_dir not in path.parents and path != self.output_dir:
            raise ArtifactError(f"Artifact path escapes output directory: {relative_path}")
        return path

    def write_text(self, relative_path: str, content: str, *, overwrite: bool | None = None) -> str:
        path = self.path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        can_overwrite = self.allow_overwrite if overwrite is None else overwrite
        if path.exists() and not can_overwrite:
            raise ArtifactError(f"Refusing to overwrite existing artifact: {path}")
        try:
            path.write_text(content, encoding="utf-8", newline="\n")
        except OSError as exc:
            raise ArtifactError(f"Failed to write artifact {path}: {exc}") from exc
        return str(path)

    def write_json(self, relative_path: str, data: Any, *, overwrite: bool | None = None) -> str:
        return self.write_text(
            relative_path,
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            overwrite=overwrite,
        )

    def read_text(self, relative_path: str) -> str:
        path = self.path(relative_path)
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ArtifactError(f"Failed to read artifact {path}: {exc}") from exc

    def read_json(self, relative_path: str) -> Any:
        return json.loads(self.read_text(relative_path))


def public_artifact(relative_path: str) -> dict[str, str]:
    return {"path": relative_path, "visibility": "agent_visible"}


def private_artifact(relative_path: str) -> dict[str, str]:
    return {"path": relative_path, "visibility": "private_orchestrator"}
