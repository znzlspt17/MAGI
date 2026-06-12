"""Configuration and private model routing."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from magi_spec.core.errors import MagiError


AGENT_KEYS = [
    "interviewer",
    "critic",
    "compiler",
    "critical_reporter",
]
VALID_WEB_SEARCH_MODES = {"auto", "on", "off"}
VALID_PIPELINE_VERSIONS = {"v2"}
DEFAULT_PIPELINE_VERSION = "v2"


@dataclass(slots=True)
class ModelRoute:
    provider: str
    model: str

    def to_dict(self) -> dict[str, str]:
        return {"provider": self.provider, "model": self.model}


@dataclass(slots=True)
class MagiConfig:
    model_routing: dict[str, ModelRoute] = field(default_factory=dict)
    analysis_language: str = "ko"
    final_spec_language: str = "en"
    web_search: str = "auto"
    command_execution: bool = False
    project_scan: bool = True
    max_critic_passes: int = 2
    pipeline_version: str = DEFAULT_PIPELINE_VERSION

    @classmethod
    def default(cls) -> "MagiConfig":
        """Production default: OpenAI provider."""
        default_model = os.environ.get("MAGI_SPEC_OPENAI_MODEL", "gpt-5.4-nano")
        return cls(
            model_routing={
                agent: ModelRoute(provider="openai", model=default_model)
                for agent in AGENT_KEYS
            },
        )

    @classmethod
    def mock(cls) -> "MagiConfig":
        """Test config using mock provider."""
        return cls(
            model_routing={
                agent: ModelRoute(provider="mock", model="deterministic-test-model")
                for agent in AGENT_KEYS
            },
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "MagiConfig":
        config_path = Path(path)
        raw = config_path.read_text(encoding="utf-8")
        if config_path.suffix.lower() == ".json":
            data = json.loads(raw)
        else:
            data = yaml.safe_load(raw) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MagiConfig":
        default_model = os.environ.get("MAGI_SPEC_OPENAI_MODEL", "gpt-5.4-nano")
        base = cls(
            model_routing={
                agent: ModelRoute(provider="openai", model=default_model)
                for agent in AGENT_KEYS
            },
        )
        routing_data = data.get("model_routing") or data.get("models") or {}
        if routing_data:
            for agent, route in routing_data.items():
                if agent in AGENT_KEYS:
                    base.model_routing[agent] = ModelRoute(
                        provider=str(route.get("provider", "openai")),
                        model=str(route.get("model", "default-model")),
                    )
        review = data.get("review", {})
        language = data.get("language", {})
        capabilities = data.get("capabilities", {})
        pipeline = data.get("pipeline", {})
        base.max_critic_passes = int(review.get("max_critic_passes", base.max_critic_passes))
        base.analysis_language = str(language.get("analysis", base.analysis_language))
        base.final_spec_language = str(language.get("final_spec", base.final_spec_language))
        base.pipeline_version = str(pipeline.get("version", base.pipeline_version))
        base.web_search = _normalize_web_search_mode(
            capabilities.get("web_search", base.web_search)
        )
        base.command_execution = bool(capabilities.get("command_execution", base.command_execution))
        base.project_scan = bool(capabilities.get("project_scan", base.project_scan))
        base.validate()
        return base

    def private_model_assignments(self) -> dict[str, dict[str, str]]:
        return {agent: route.to_dict() for agent, route in self.model_routing.items()}

    def validate(self) -> None:
        if self.web_search not in VALID_WEB_SEARCH_MODES:
            raise MagiError(
                f"Invalid web_search mode '{self.web_search}'. "
                "Allowed values are: auto, on, off."
            )
        if self.pipeline_version not in VALID_PIPELINE_VERSIONS:
            raise MagiError(
                f"Invalid pipeline_version '{self.pipeline_version}'. "
                "Only 'v2' is supported by the current runtime."
            )
        if not (1 <= self.max_critic_passes <= 3):
            raise MagiError(
                f"max_critic_passes must be between 1 and 3, got {self.max_critic_passes}."
            )


def _normalize_web_search_mode(value: Any) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if value is None:
        return "auto"
    return str(value)
