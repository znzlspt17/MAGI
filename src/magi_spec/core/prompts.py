"""Prompt file loading helpers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from magi_spec.core.errors import MagiError


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


@lru_cache(maxsize=None)
def load_prompt(prompt_id: str) -> str:
    """Load a bundled Markdown prompt by id without exposing routing metadata."""

    if not prompt_id or "/" in prompt_id or "\\" in prompt_id:
        raise MagiError(f"Invalid prompt id: {prompt_id!r}")
    path = (PROMPT_DIR / f"{prompt_id}.md").resolve()
    if PROMPT_DIR not in path.parents:
        raise MagiError(f"Prompt path escapes prompt directory: {prompt_id!r}")
    if not path.exists():
        raise MagiError(f"Prompt file does not exist: {path}")
    return path.read_text(encoding="utf-8")
