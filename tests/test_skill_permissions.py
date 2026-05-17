from __future__ import annotations

import pytest

from magi_spec.core.errors import PermissionDeniedError
from magi_spec.skills.registry import build_default_skill_registry


def test_melchior_cannot_use_balthasar_only_skill() -> None:
    registry = build_default_skill_registry()

    with pytest.raises(PermissionDeniedError):
        registry.assert_allowed("melchior", "parse_intent")


def test_spec_composer_cannot_run_web_search() -> None:
    registry = build_default_skill_registry()

    with pytest.raises(PermissionDeniedError):
        registry.assert_allowed("spec_composer", "web_search")
