from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conftest import read_json
from magi_spec.core.config import MagiConfig, ModelRoute
from magi_spec.engine import MagiSpecEngine
from magi_spec.providers.base import LLMProvider, ProviderFactory


class AnalysisScriptedProvider(LLMProvider):
    provider_name = "mock"

    def __init__(self) -> None:
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
        if model == "analysis-model":
            return json.dumps(
                {
                    "intent_parse": "# 의도 분석\n\n요청을 실행 가능한 명세로 전환합니다.",
                    "requirement_lock": "# 요구사항 잠금\n\n- 승인 전 최종화 금지\n- 범위 확장 금지",
                    "scope_classification": "# 범위 분류\n\n- Mandatory: 핵심 요구사항\n- Out of Scope: 배포",
                    "assumptions": ["기존 프로젝트 관례를 우선합니다.", "테스트 가능성을 유지합니다."],
                    "blocking_questions": ["외부 API 사용 여부를 확인해야 합니다."],
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "status": "PASS",
                "content": "default provider response",
                "section_status": {
                    "mission": "PASS",
                    "scope": "PASS",
                    "architecture": "PASS",
                    "test_plan": "PASS",
                    "agent_instructions": "PASS",
                },
            }
        )


def build_factory(provider: LLMProvider) -> ProviderFactory:
    factory = ProviderFactory()
    factory.register(provider)
    return factory


def test_analysis_packet_from_provider_updates_artifacts(tmp_path: Path) -> None:
    config = MagiConfig.mock()
    config.model_routing["balthasar"] = ModelRoute(provider="mock", model="analysis-model")
    provider = AnalysisScriptedProvider()
    engine = MagiSpecEngine(config=config, providers=build_factory(provider))
    output = tmp_path / "out"

    result = engine.generate_from_text(
        text="Build an implementation-ready specification.",
        output_dir=str(output),
        web_search_mode="off",
    )

    state = read_json(output / "state" / "magi_state.json")
    intent_text = (output / "analysis" / "01_intent_parse.ko.md").read_text(encoding="utf-8")
    lock_text = (output / "analysis" / "02_requirement_lock.ko.md").read_text(encoding="utf-8")
    scope_text = (output / "analysis" / "03_scope_classification.ko.md").read_text(encoding="utf-8")

    assert result.status == "PASS_PENDING_USER_APPROVAL"
    assert "요청을 실행 가능한 명세로 전환합니다." in intent_text
    assert "승인 전 최종화 금지" in lock_text
    assert "Mandatory: 핵심 요구사항" in scope_text
    assert state["assumptions"] == ["기존 프로젝트 관례를 우선합니다.", "테스트 가능성을 유지합니다."]
    assert state["blocking_questions"] == ["외부 API 사용 여부를 확인해야 합니다."]
    assert any(call["model"] == "analysis-model" for call in provider.calls)
