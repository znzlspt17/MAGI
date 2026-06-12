from __future__ import annotations

import pytest

from magi_spec.core.errors import PermissionDeniedError
from magi_spec.skills.registry import build_default_skill_registry


def test_interviewer_can_parse_intent() -> None:
    registry = build_default_skill_registry()
    registry.assert_allowed("interviewer", "parse_intent")


def test_compiler_cannot_run_web_search() -> None:
    registry = build_default_skill_registry()

    with pytest.raises(PermissionDeniedError):
        registry.assert_allowed("compiler", "web_search")


def test_critic_cannot_compose_final_spec() -> None:
    registry = build_default_skill_registry()

    with pytest.raises(PermissionDeniedError):
        registry.assert_allowed("critic", "compose_final_spec")
