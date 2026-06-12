from __future__ import annotations

import pytest

from magi_spec.core.config import MagiConfig
from magi_spec.core.errors import MagiError


def test_config_rejects_invalid_web_search_mode() -> None:
    with pytest.raises(MagiError, match="Invalid web_search mode"):
        MagiConfig.from_dict({"capabilities": {"web_search": "sometimes"}})


def test_config_normalizes_bool_web_search_mode() -> None:
    config_off = MagiConfig.from_dict({"capabilities": {"web_search": False}})
    config_on = MagiConfig.from_dict({"capabilities": {"web_search": True}})

    assert config_off.web_search == "off"
    assert config_on.web_search == "on"


def test_config_rejects_invalid_max_critic_passes() -> None:
    with pytest.raises(MagiError, match="max_critic_passes"):
        MagiConfig.from_dict({"review": {"max_critic_passes": 10}})
