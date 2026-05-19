from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from magi_spec.core.config import MagiConfig, ModelRoute
from magi_spec.engine import MagiSpecEngine
from magi_spec.providers.base import LLMProvider, ProviderFactory


class RoutingCaptureProvider(LLMProvider):
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
        self.calls.append({"model": model, "temperature": temperature, "messages": messages})
        if "spec" in model:
            return json.dumps(
                {
                    "spec_markdown": "\n".join(
                        [
                            "# Final Agent Specification",
                            "## 1. Mission",
                            "## 2. Background",
                            "## 3. User Intent",
                            "## 4. Scope",
                            "### 4.1 In Scope",
                            "### 4.2 Out of Scope",
                            "## 5. Definitions",
                            "## 6. Evidence Summary",
                            "## 7. Mandatory Requirements",
                            "## 8. Recommended Requirements",
                            "## 9. Optional Requirements",
                            "## 10. Forbidden Behaviors",
                            "## 11. Input Contract",
                            "## 12. Output Contract",
                            "## 13. Architecture",
                            "## 14. Module Responsibilities",
                            "## 15. Data Flow",
                            "## 16. Error Handling Policy",
                            "## 17. Configuration Policy",
                            "## 18. Persistence / Artifact Policy",
                            "## 19. Implementation Order",
                            "## 20. Acceptance Criteria",
                            "## 21. Test Plan",
                            "## 22. Manual Verification Checklist",
                            "## 23. Instructions for AI Coding Agent",
                        ]
                    )
                }
            )
        if "analysis" in model:
            return json.dumps(
                {
                    "intent_parse": "# 의도 분석\n\n요청 분석",
                    "requirement_lock": "# 요구사항 잠금\n\n- 승인 전 최종화 금지",
                    "scope_classification": "# 범위 분류\n\n- Mandatory: 핵심",
                    "assumptions": ["기존 관례 준수"],
                    "blocking_questions": [],
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "status": "PASS",
                "content": "review ok",
                "section_status": {
                    "mission": "PASS",
                    "scope": "PASS",
                    "architecture": "PASS",
                    "test_plan": "PASS",
                    "agent_instructions": "PASS",
                },
            }
        )


def _factory(provider: LLMProvider) -> ProviderFactory:
    factory = ProviderFactory()
    factory.register(provider)
    return factory


def test_agent_specific_models_are_used_in_provider_calls(tmp_path: Path) -> None:
    config = MagiConfig.mock()
    config.model_routing["melchior"] = ModelRoute(provider="mock", model="melchior-model")
    config.model_routing["balthasar"] = ModelRoute(provider="mock", model="balthasar-analysis-model")
    config.model_routing["casper"] = ModelRoute(provider="mock", model="casper-model")
    config.model_routing["conflict_resolver"] = ModelRoute(provider="mock", model="conflict-model")
    config.model_routing["spec_composer"] = ModelRoute(provider="mock", model="spec-model")
    config.model_routing["critical_reporter"] = ModelRoute(provider="mock", model="critical-model")

    provider = RoutingCaptureProvider()
    engine = MagiSpecEngine(config=config, providers=_factory(provider))
    output = tmp_path / "out"
    result = engine.generate_from_text(
        text="Build package.",
        output_dir=str(output),
        web_search_mode="off",
    )

    used_models = {call["model"] for call in provider.calls}
    assert result.status == "PASS_PENDING_USER_APPROVAL"
    assert "melchior-model" in used_models
    assert "balthasar-analysis-model" in used_models
    assert "casper-model" in used_models
    assert "conflict-model" in used_models
    assert "spec-model" in used_models
