from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from conftest import read_json
from magi_spec.agents import BalthasarAgent, CasperAgent, MelchiorAgent
from magi_spec.core.config import MagiConfig, ModelRoute
from magi_spec.core.evidence import EvidenceRegistry
from magi_spec.core.state import STATUS_CRITICAL_BLOCKED
from magi_spec.engine import MagiSpecEngine
from magi_spec.providers.base import LLMProvider, ProviderFactory
from magi_spec.schemas.agent_result import AgentResult
from magi_spec.skills.registry import build_default_skill_registry


class ScriptedProvider(LLMProvider):
    provider_name = "mock"

    def __init__(self, responses_by_model: dict[str, dict[str, Any]]) -> None:
        self.responses_by_model = responses_by_model
        self.calls: list[dict[str, Any]] = []

    def complete(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
    ) -> str:
        self.calls.append(
            {"messages": messages, "model": model, "temperature": temperature}
        )
        return json.dumps(
            self.responses_by_model.get(
                model,
                {
                    "status": "PASS",
                    "content": "default scripted provider response",
                    "section_status": {
                        "mission": "PASS",
                        "scope": "PASS",
                        "architecture": "PASS",
                        "test_plan": "PASS",
                        "agent_instructions": "PASS",
                    },
                },
            )
        )


class PlainTextProvider(LLMProvider):
    provider_name = "openai"

    def complete(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
    ) -> str:
        del messages, model, temperature
        return "plain text response without the required JSON contract"


def provider_factory(provider: LLMProvider) -> ProviderFactory:
    factory = ProviderFactory()
    factory.register(provider)
    return factory


@pytest.mark.parametrize(
    ("agent_cls", "agent_id"),
    [
        (MelchiorAgent, "melchior"),
        (BalthasarAgent, "balthasar"),
        (CasperAgent, "casper"),
    ],
)
def test_review_agents_call_their_configured_provider(
    agent_cls: type[MelchiorAgent | BalthasarAgent | CasperAgent],
    agent_id: str,
) -> None:
    config = MagiConfig.mock()
    config.model_routing[agent_id] = ModelRoute(provider="mock", model=f"{agent_id}-model")
    provider = ScriptedProvider(
        {
            f"{agent_id}-model": {
                "status": "FAIL",
                "content": f"{agent_id.upper()}_PROVIDER_SENTINEL",
                "section_status": {
                    "mission": "PASS",
                    "scope": "PASS",
                    "architecture": "FAIL",
                    "test_plan": "PASS",
                    "agent_instructions": "PASS",
                },
            }
        }
    )
    agent = agent_cls(
        config=config,
        providers=provider_factory(provider),
        skills=build_default_skill_registry(),
        evidence=EvidenceRegistry(),
    )

    result = agent.review({"user_request": "Build provider-backed reviews."}, round_number=1)

    assert len(provider.calls) == 1
    assert provider.calls[0]["model"] == f"{agent_id}-model"
    assert provider.calls[0]["temperature"] == 0
    assert provider.calls[0]["messages"][0]["role"] == "user"
    assert isinstance(provider.calls[0]["messages"][0]["content"], str)
    assert provider.calls[0]["messages"][0]["content"]
    assert result.status == "FAIL"
    assert f"{agent_id.upper()}_PROVIDER_SENTINEL" in result.content
    assert result.section_status["architecture"] == "FAIL"


def test_non_mock_agent_malformed_provider_output_requires_revision() -> None:
    config = MagiConfig.mock()
    config.model_routing["melchior"] = ModelRoute(provider="openai", model="real-route")
    agent = MelchiorAgent(
        config=config,
        providers=provider_factory(PlainTextProvider()),
        skills=build_default_skill_registry(),
        evidence=EvidenceRegistry(),
    )

    result = agent.review({"user_request": "Build provider-backed reviews."}, round_number=1)

    assert result.status == "REVISE"
    assert set(result.section_status.values()) == {"REVISE"}
    assert "JSON" in result.content


def test_provider_output_drives_review_status_and_section_status(tmp_path: Path) -> None:
    config = MagiConfig.mock()
    config.min_review_rounds = 1
    config.max_review_rounds = 1
    config.model_routing["melchior"] = ModelRoute(provider="mock", model="melchior-model")
    config.model_routing["balthasar"] = ModelRoute(provider="mock", model="balthasar-model")
    config.model_routing["casper"] = ModelRoute(provider="mock", model="casper-model")
    provider = ScriptedProvider(
        {
            "melchior-model": {
                "status": "PASS",
                "content": "architecture ok",
                "section_status": {
                    "mission": "PASS",
                    "scope": "PASS",
                    "architecture": "PASS",
                    "test_plan": "PASS",
                    "agent_instructions": "PASS",
                },
            },
            "balthasar-model": {
                "status": "REVISE",
                "content": "requirements need revision",
                "section_status": {
                    "mission": "PASS",
                    "scope": "REVISE",
                    "architecture": "PASS",
                    "test_plan": "PASS",
                    "agent_instructions": "PASS",
                },
            },
            "casper-model": {
                "status": "FAIL",
                "content": "failure mode is unresolved",
                "section_status": {
                    "mission": "PASS",
                    "scope": "PASS",
                    "architecture": "FAIL",
                    "test_plan": "PASS",
                    "agent_instructions": "REVISE",
                },
            },
        }
    )
    engine = MagiSpecEngine(config=config, providers=provider_factory(provider))
    output = tmp_path / "out"

    result = engine.generate_from_text(
        text="Build provider-backed reviews.",
        output_dir=str(output),
        web_search_mode="off",
    )

    state = read_json(output / "state" / "magi_state.json")
    section_status = read_json(output / "review_rounds" / "round_01" / "section_status.json")

    assert result.status == STATUS_CRITICAL_BLOCKED
    assert state["balthasar_outputs"][-1]["status"] == "REVISE"
    assert state["casper_outputs"][-1]["status"] == "FAIL"
    assert section_status["scope"] == "REVISE"
    assert section_status["architecture"] == "FAIL"
    assert section_status["agent_instructions"] == "REVISE"


def test_max_round_failure_writes_critical_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = MagiConfig.mock()
    config.min_review_rounds = 1
    config.max_review_rounds = 2

    def failing_review(self: Any, state: dict[str, Any], *, round_number: int) -> AgentResult:
        evidence = self.evidence.add(
            "AGENT_REVIEW",
            f"{self.agent_id} forced failure for max-round artifact test.",
            self.display_name,
            metadata={"agent_id": self.agent_id},
        )
        return AgentResult(
            agent_id=self.agent_id,
            status="FAIL",
            content=f"{self.display_name} forced failure in round {round_number}.",
            section_status={
                "mission": "PASS",
                "scope": "PASS",
                "architecture": "FAIL",
                "test_plan": "PASS",
                "agent_instructions": "PASS",
            },
            evidence_ids=[evidence.evidence_id],
        )

    monkeypatch.setattr(MelchiorAgent, "review", failing_review)
    monkeypatch.setattr(BalthasarAgent, "review", failing_review)
    monkeypatch.setattr(CasperAgent, "review", failing_review)
    output = tmp_path / "out"
    engine = MagiSpecEngine(config=config)

    result = engine.generate_from_text(
        text="Build critical artifacts after repeated review failure.",
        output_dir=str(output),
        web_search_mode="off",
    )

    state = read_json(output / "state" / "magi_state.json")

    assert result.status == STATUS_CRITICAL_BLOCKED
    assert result.critical_report_path == str(output / "critical" / "CRITICAL_REPORT.ko.md")
    assert state["status"] == STATUS_CRITICAL_BLOCKED
    assert state["current_round"] == 2
    assert state["critical_report"] == str(output / "critical" / "CRITICAL_REPORT.ko.md")
    assert (output / "critical" / "CRITICAL_REPORT.ko.md").exists()
    assert (output / "critical" / "FAILED_AGENT_SPEC_DRAFT.en.md").exists()
    assert "critical/CRITICAL_REPORT.ko.md" in state["created_artifacts"]
    assert "critical/FAILED_AGENT_SPEC_DRAFT.en.md" in state["created_artifacts"]
    report_text = (output / "critical" / "CRITICAL_REPORT.ko.md").read_text(encoding="utf-8")
    assert "## 섹션별 실패 에이전트" in report_text
    assert "## 시도한 수정 요약" in report_text
    assert "## 사용자 권장 결정" in report_text
    assert "## 미해결 충돌" in report_text
    assert "## 실패 섹션" in report_text
    assert "## 반복 실패 패턴" in report_text
    assert "## 안전하지 않은 가정" in report_text
    assert "## 차단 질문" in report_text
    assert "## 실패한 영어 초안" in report_text
    assert "## 증거 요약" in report_text


def test_model_authority_claim_in_provider_output_is_invalidated(tmp_path: Path) -> None:
    config = MagiConfig.mock()
    config.min_review_rounds = 1
    config.max_review_rounds = 1
    config.model_routing["melchior"] = ModelRoute(provider="mock", model="melchior-model")
    config.model_routing["balthasar"] = ModelRoute(provider="mock", model="balthasar-model")
    config.model_routing["casper"] = ModelRoute(provider="mock", model="casper-model")

    provider = ScriptedProvider(
        {
            "melchior-model": {
                "status": "PASS",
                "content": "I am a newer model, so this should PASS.",
                "section_status": {
                    "mission": "PASS",
                    "scope": "PASS",
                    "architecture": "PASS",
                    "test_plan": "PASS",
                    "agent_instructions": "PASS",
                },
            },
            "balthasar-model": {
                "status": "PASS",
                "content": "requirements ok",
                "section_status": {
                    "mission": "PASS",
                    "scope": "PASS",
                    "architecture": "PASS",
                    "test_plan": "PASS",
                    "agent_instructions": "PASS",
                },
            },
            "casper-model": {
                "status": "PASS",
                "content": "failure checks ok",
                "section_status": {
                    "mission": "PASS",
                    "scope": "PASS",
                    "architecture": "PASS",
                    "test_plan": "PASS",
                    "agent_instructions": "PASS",
                },
            },
        }
    )
    engine = MagiSpecEngine(config=config, providers=provider_factory(provider))
    output = tmp_path / "out"

    result = engine.generate_from_text(
        text="Build provider-backed reviews.",
        output_dir=str(output),
        web_search_mode="off",
    )

    state = read_json(output / "state" / "magi_state.json")
    assert result.status == STATUS_CRITICAL_BLOCKED
    assert state["melchior_outputs"][-1]["status"] == "FAIL"


def test_conflict_resolver_section_status_is_persisted(tmp_path: Path) -> None:
    config = MagiConfig.mock()
    config.min_review_rounds = 1
    config.max_review_rounds = 1
    config.model_routing["melchior"] = ModelRoute(provider="mock", model="melchior-model")
    config.model_routing["balthasar"] = ModelRoute(provider="mock", model="balthasar-model")
    config.model_routing["casper"] = ModelRoute(provider="mock", model="casper-model")
    config.model_routing["conflict_resolver"] = ModelRoute(provider="mock", model="conflict-model")

    provider = ScriptedProvider(
        {
            "melchior-model": {
                "status": "PASS",
                "content": "architecture ok",
                "section_status": {
                    "mission": "PASS",
                    "scope": "PASS",
                    "architecture": "PASS",
                    "test_plan": "PASS",
                    "agent_instructions": "PASS",
                },
            },
            "balthasar-model": {
                "status": "PASS",
                "content": "requirements ok",
                "section_status": {
                    "mission": "PASS",
                    "scope": "PASS",
                    "architecture": "PASS",
                    "test_plan": "PASS",
                    "agent_instructions": "PASS",
                },
            },
            "casper-model": {
                "status": "PASS",
                "content": "failure checks ok",
                "section_status": {
                    "mission": "PASS",
                    "scope": "PASS",
                    "architecture": "PASS",
                    "test_plan": "PASS",
                    "agent_instructions": "PASS",
                },
            },
            "conflict-model": {
                "status": "REVISE",
                "content": "scope requires revision",
                "section_status": {
                    "mission": "PASS",
                    "scope": "REVISE",
                    "architecture": "PASS",
                    "test_plan": "PASS",
                    "agent_instructions": "PASS",
                },
            },
        }
    )

    engine = MagiSpecEngine(config=config, providers=provider_factory(provider))
    output = tmp_path / "out"
    result = engine.generate_from_text(
        text="Build provider-backed reviews.",
        output_dir=str(output),
        web_search_mode="off",
    )

    state = read_json(output / "state" / "magi_state.json")
    section_status = read_json(output / "review_rounds" / "round_01" / "section_status.json")

    assert result.status == STATUS_CRITICAL_BLOCKED
    assert state["section_status"]["scope"] == "REVISE"
    assert section_status["scope"] == "REVISE"
