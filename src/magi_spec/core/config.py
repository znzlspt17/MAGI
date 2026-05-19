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
    "melchior",
    "balthasar",
    "casper",
    "conflict_resolver",
    "spec_composer",
    "critical_reporter",
]
VALID_WEB_SEARCH_MODES = {"auto", "on", "off"}


@dataclass(slots=True)
class ModelRoute:
    provider: str
    model: str

    def to_dict(self) -> dict[str, str]:
        return {"provider": self.provider, "model": self.model}


@dataclass(slots=True)
class MagiConfig:
    model_routing: dict[str, ModelRoute] = field(default_factory=dict)
    min_review_rounds: int = 3
    max_review_rounds: int = 10
    analysis_language: str = "ko"
    final_spec_language: str = "en"
    web_search: str = "auto"
    command_execution: bool = False
    project_scan: bool = True

    @classmethod
    def default(cls) -> "MagiConfig":
        default_model = os.environ.get("MAGI_SPEC_OPENAI_MODEL", "gpt-4.1-mini")
        return cls(
            model_routing={
                agent: ModelRoute(provider="openai", model=default_model)
                for agent in AGENT_KEYS
            }
        )

    @classmethod
    def mock(cls) -> "MagiConfig":
        return cls(
            model_routing={
                agent: ModelRoute(provider="mock", model="deterministic-test-model")
                for agent in AGENT_KEYS
            }
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
        base = cls.default()
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
        base.min_review_rounds = int(review.get("min_review_rounds", base.min_review_rounds))
        base.max_review_rounds = int(review.get("max_review_rounds", base.max_review_rounds))
        base.analysis_language = str(language.get("analysis", base.analysis_language))
        base.final_spec_language = str(language.get("final_spec", base.final_spec_language))
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
        if self.min_review_rounds < 1:
            raise MagiError(f"min_review_rounds must be >= 1, got {self.min_review_rounds}.")
        if self.max_review_rounds < 1:
            raise MagiError(f"max_review_rounds must be >= 1, got {self.max_review_rounds}.")
        if self.min_review_rounds > self.max_review_rounds:
            raise MagiError(
                "min_review_rounds cannot be greater than max_review_rounds. "
                f"Got min={self.min_review_rounds}, max={self.max_review_rounds}."
            )
        if self.web_search not in VALID_WEB_SEARCH_MODES:
            raise MagiError(
                f"Invalid web_search mode '{self.web_search}'. "
                "Allowed values are: auto, on, off."
            )


def _normalize_web_search_mode(value: Any) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if value is None:
        return "auto"
    return str(value)
