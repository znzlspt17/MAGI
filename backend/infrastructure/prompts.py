"""Prompt file loading helpers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from backend.errors import Error


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
QUESTION_PROMPTS = frozenset({"interviewer", "checklist_critic", "review_resolution"})


@lru_cache(maxsize=None)
def load_prompt(prompt_id: str) -> str:
    """단계 지침에 필요한 공통 질문 계약만 한 번 조합한다."""
    content = _read_prompt(prompt_id)
    if prompt_id in QUESTION_PROMPTS:
        return content.rstrip() + "\n\n" + _read_prompt("_question_contract")
    return content


def _read_prompt(prompt_id: str) -> str:
    """공통 조각에도 단계 파일과 동일한 경로 검증을 적용한다."""

    if not prompt_id or "/" in prompt_id or "\\" in prompt_id:
        raise Error(f"Invalid prompt id: {prompt_id!r}")
    path = (PROMPT_DIR / f"{prompt_id}.md").resolve()
    if PROMPT_DIR not in path.parents:
        raise Error(f"Prompt path escapes prompt directory: {prompt_id!r}")
    if not path.exists():
        raise Error(f"Prompt file does not exist: {path}")
    return path.read_text(encoding="utf-8")
