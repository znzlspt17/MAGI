from __future__ import annotations

import json
from pathlib import Path

import pytest

from magi_spec.core.config import MagiConfig
from magi_spec.engine import MagiSpecEngine


@pytest.fixture
def mock_engine() -> MagiSpecEngine:
    return MagiSpecEngine(config=MagiConfig.mock())


@pytest.fixture
def mock_engine_v2() -> MagiSpecEngine:
    return MagiSpecEngine(config=MagiConfig.mock())


@pytest.fixture
def mock_config_file(tmp_path: Path) -> Path:
    path = tmp_path / "mock_config.yaml"
    path.write_text(
        """
model_routing:
  interviewer:
    provider: mock
    model: deterministic
  critic:
    provider: mock
    model: deterministic
  compiler:
    provider: mock
    model: deterministic
  critical_reporter:
    provider: mock
    model: deterministic
review:
  max_critic_passes: 2
capabilities:
  web_search: off
  command_execution: false
""".strip(),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def mock_config_v2_file(tmp_path: Path) -> Path:
    return mock_config_file(tmp_path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
