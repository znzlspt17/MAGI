"""Prompt file loading helpers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from backend.errors import Error


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


@lru_cache(maxsize=None)
def load_prompt(prompt_id: str) -> str:
    """Load a bundled Markdown prompt by id without exposing routing metadata."""

    if not prompt_id or "/" in prompt_id or "\\" in prompt_id:
        raise Error(f"Invalid prompt id: {prompt_id!r}")
    path = (PROMPT_DIR / f"{prompt_id}.md").resolve()
    if PROMPT_DIR not in path.parents:
        raise Error(f"Prompt path escapes prompt directory: {prompt_id!r}")
    if not path.exists():
        raise Error(f"Prompt file does not exist: {path}")
    return path.read_text(encoding="utf-8")
