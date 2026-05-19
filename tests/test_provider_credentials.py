from __future__ import annotations

from pathlib import Path

import pytest

from magi_spec.core.config import MagiConfig
from magi_spec.core.errors import MagiError, MissingCredentialError
from magi_spec.engine import MagiSpecEngine
from magi_spec.providers.base import LLMProvider, ProviderFactory


class FakeOpenAIProvider(LLMProvider):
    provider_name = "openai"

    def complete(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
    ) -> str:
        del messages, model, temperature
        return (
            '{"status":"PASS","content":"test provider review",'
            '"section_status":{"mission":"PASS","scope":"PASS","architecture":"PASS",'
            '"test_plan":"PASS","agent_instructions":"PASS"}}'
        )


def fake_openai_factory() -> ProviderFactory:
    factory = ProviderFactory()
    factory.register(FakeOpenAIProvider())
    return factory


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
    engine = MagiSpecEngine(config=MagiConfig.default(), providers=fake_openai_factory())

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


def test_api_rejects_invalid_web_search_mode(tmp_path: Path) -> None:
    engine = MagiSpecEngine(config=MagiConfig.mock())
    with pytest.raises(MagiError, match="Invalid web_search_mode"):
        engine.generate_from_text(
            text="Build package.",
            output_dir=str(tmp_path / "out"),
            web_search_mode="sometimes",
        )


def test_engine_rejects_invalid_round_config_on_generate(tmp_path: Path) -> None:
    config = MagiConfig.mock()
    config.min_review_rounds = 0
    engine = MagiSpecEngine(config=config)
    with pytest.raises(MagiError, match="min_review_rounds must be >= 1"):
        engine.generate_from_text(
            text="Build package.",
            output_dir=str(tmp_path / "out"),
            web_search_mode="off",
        )
