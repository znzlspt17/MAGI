from __future__ import annotations

from pathlib import Path

import pytest

from magi_spec.core.config import MagiConfig
from magi_spec.core.errors import MagiError, MissingCredentialError
from magi_spec.engine import MagiSpecEngine


def test_openai_default_requires_api_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    engine = MagiSpecEngine(config=MagiConfig.default())

    with pytest.raises(MissingCredentialError):
        engine.generate_from_text(
            text="Build package.",
            output_dir=str(tmp_path / "out"),
            web_search_mode="off",
        )


def test_openai_provider_runtime_accepts_openai_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    engine = MagiSpecEngine(config=MagiConfig.default())

    result = engine.generate_from_text(
        text="Build package.",
        output_dir=str(tmp_path / "out"),
        web_search_mode="off",
    )

    assert result.status == "PASS_PENDING_USER_APPROVAL"


def test_mock_provider_does_not_require_api_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    engine = MagiSpecEngine(config=MagiConfig.mock())

    result = engine.generate_from_text(
        text="Build package.",
        output_dir=str(tmp_path / "out"),
        web_search_mode="off",
    )

    assert result.status == "PASS_PENDING_USER_APPROVAL"


def test_non_openai_stub_credentials_are_not_required(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = MagiConfig.mock()
    config.model_routing["melchior"].provider = "anthropic"
    engine = MagiSpecEngine(config=config)

    with pytest.raises(MagiError, match="future extension stub"):
        engine.generate_from_text(
            text="Build package.",
            output_dir=str(tmp_path / "out"),
            web_search_mode="off",
        )
