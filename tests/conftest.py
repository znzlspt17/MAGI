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
def mock_config_file(tmp_path: Path) -> Path:
    path = tmp_path / "mock_config.yaml"
    path.write_text(
        """
model_routing:
  melchior:
    provider: mock
    model: deterministic
  balthasar:
    provider: mock
    model: deterministic
  casper:
    provider: mock
    model: deterministic
  conflict_resolver:
    provider: mock
    model: deterministic
  spec_composer:
    provider: mock
    model: deterministic
  critical_reporter:
    provider: mock
    model: deterministic
review:
  min_review_rounds: 3
  max_review_rounds: 10
capabilities:
  web_search: off
  command_execution: false
""".strip(),
        encoding="utf-8",
    )
    return path


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
