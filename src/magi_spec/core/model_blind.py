"""Model-blind review validation."""

from __future__ import annotations

import re


MODEL_AUTHORITY_PATTERNS = [
    re.compile(r"\bnewer model\b", re.IGNORECASE),
    re.compile(r"\bbenchmark score\b", re.IGNORECASE),
    re.compile(r"\bmy benchmark\b", re.IGNORECASE),
    re.compile(r"\bcontext window\b", re.IGNORECASE),
    re.compile(r"\bpricing tier\b", re.IGNORECASE),
    re.compile(r"\b(openai|claude|gemini)\s+is\s+better\b", re.IGNORECASE),
    re.compile(r"\b(model|provider)\s+authority\b", re.IGNORECASE),
]


def contains_model_authority_claim(text: str) -> bool:
    return any(pattern.search(text) for pattern in MODEL_AUTHORITY_PATTERNS)
