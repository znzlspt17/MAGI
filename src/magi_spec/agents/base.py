"""Base agent behavior."""

from __future__ import annotations

from magi_spec.core.config import MagiConfig
from magi_spec.core.evidence import EvidenceRegistry
from magi_spec.core.state import WorkflowState
from magi_spec.providers.base import ProviderFactory
from magi_spec.schemas.agent_result import AgentResult
from magi_spec.skills.registry import SkillRegistry


DEFAULT_SECTION_STATUS = {
    "mission": "PASS",
    "scope": "PASS",
    "architecture": "PASS",
    "test_plan": "PASS",
    "agent_instructions": "PASS",
}


class BaseAgent:
    agent_id: str
    display_name: str

    def __init__(
        self,
        *,
        config: MagiConfig,
        providers: ProviderFactory,
        skills: SkillRegistry,
        evidence: EvidenceRegistry,
    ) -> None:
        self.config = config
        self.providers = providers
        self.skills = skills
        self.evidence = evidence

    def _provider_complete(self, prompt: str) -> str:
        route = self.config.model_routing[self.agent_id]
        provider = self.providers.get(route.provider)
        return provider.complete(
            [{"role": "user", "content": prompt}],
            model=route.model,
            temperature=0,
        )

    def review(self, state: WorkflowState, *, round_number: int) -> AgentResult:
        raise NotImplementedError

    def _result(self, content: str, *, evidence_summary: str) -> AgentResult:
        evidence = self.evidence.add(
            "AGENT_REVIEW",
            evidence_summary,
            self.display_name,
            metadata={"agent_id": self.agent_id},
        )
        return AgentResult(
            agent_id=self.agent_id,
            status="PASS",
            content=content,
            section_status=dict(DEFAULT_SECTION_STATUS),
            evidence_ids=[evidence.evidence_id],
        )
