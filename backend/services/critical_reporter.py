"""Critical report generation — v2 failure reporter."""

from __future__ import annotations

from backend.config import MagiConfig
from backend.infrastructure.artifact_writer import ArtifactWriter
from backend.infrastructure.evidence_registry import EvidenceRegistry
from backend.models import WorkflowState
from backend.providers.llm_provider import OpenAIProvider
from backend.services.skill_registry import SkillRegistry


class CriticalReporter:
    """SpecForge 검토 실패 보고서를 생성한다."""

    agent_id = "critical_reporter"

    def __init__(
        self,
        *,
        config: MagiConfig,
        provider: OpenAIProvider,
        skills: SkillRegistry,
        evidence: EvidenceRegistry,
    ) -> None:
        self.config = config
        self.provider = provider
        self.skills = skills
        self.evidence = evidence

    def generate(
        self,
        state: WorkflowState,
        *,
        writer: ArtifactWriter | None = None,
    ) -> str:
        self.skills.assert_allowed(self.agent_id, "generate_critical_report")
        from backend.services.review_resolution import failure_report
        return failure_report(state)
