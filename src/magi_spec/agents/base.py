"""Base agent behavior."""

from __future__ import annotations

from magi_spec.core.agent_context import build_agent_visible_context
from magi_spec.core.config import MagiConfig
from magi_spec.core.evidence import EvidenceRegistry
from magi_spec.core.model_blind import contains_model_authority_claim
from magi_spec.core.prompts import load_prompt
from magi_spec.core.provider_output import extract_json_object
from magi_spec.core.state import WorkflowState
from magi_spec.providers.base import ProviderFactory
from magi_spec.schemas.agent_result import AgentResult
from magi_spec.schemas.provider_packets import ReviewPacket
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
    prompt_id: str

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

    def _review_with_provider(
        self,
        state: WorkflowState,
        *,
        round_number: int,
        fallback_content: str,
        evidence_summary: str,
    ) -> AgentResult:
        route = self.config.model_routing[self.agent_id]
        raw_output = self._provider_complete(
            self._build_review_prompt(state, round_number=round_number)
        )
        status, content, section_status = self._parse_review_output(
            raw_output,
            fallback_content=fallback_content,
            allow_static_fallback=route.provider == "mock",
        )
        return self._result(
            content,
            status=status,
            section_status=section_status,
            evidence_summary=evidence_summary,
        )

    def _build_review_prompt(self, state: WorkflowState, *, round_number: int) -> str:
        context = build_agent_visible_context(
            state,
            agent_id=self.agent_id,
            round_number=round_number,
        )
        return "\n\n".join(
            [
                load_prompt(self.prompt_id),
                "Agent-visible context follows. It intentionally excludes private routing metadata.",
                context,
                "Return only JSON with keys: status, section_status, content.",
                "status must be PASS, REVISE, or FAIL.",
                "section_status values must be PASS, REVISE, or FAIL for these sections: "
                + ", ".join(DEFAULT_SECTION_STATUS),
                "content must be a concise Korean review report and must not mention model or provider identity.",
            ]
        )

    def _parse_review_output(
        self,
        raw_output: str,
        *,
        fallback_content: str,
        allow_static_fallback: bool,
    ) -> tuple[str, str, dict[str, str]]:
        parsed = extract_json_object(raw_output)
        packet = ReviewPacket.from_provider_dict(
            parsed,
            fallback_status="PASS",
            fallback_content=fallback_content,
            fallback_sections=dict(DEFAULT_SECTION_STATUS),
            allow_static_fallback=allow_static_fallback,
            malformed_error_title=f"# {self.display_name} 구조화 응답 오류",
        )
        status = packet.status
        content = packet.content
        section_status = packet.section_status

        if contains_model_authority_claim(raw_output) or contains_model_authority_claim(content):
            status = "FAIL"
            section_status = {key: "FAIL" for key in DEFAULT_SECTION_STATUS}
            content = "\n".join(
                [
                    f"# {self.display_name} 모델 블라인드 검토 실패",
                    "",
                    "- 검토 결과에 모델 또는 제공자 권위 주장이 포함되어 무효 처리했습니다.",
                    "- 판단 근거는 사용자 요구사항, 증거, 아키텍처 제약, 실패 모드여야 합니다.",
                ]
            )
        return status, content, section_status

    def _result(
        self,
        content: str,
        *,
        status: str = "PASS",
        section_status: dict[str, str] | None = None,
        evidence_summary: str,
    ) -> AgentResult:
        evidence = self.evidence.add(
            "AGENT_REVIEW",
            evidence_summary,
            self.display_name,
            metadata={"agent_id": self.agent_id},
        )
        return AgentResult(
            agent_id=self.agent_id,
            status=status,
            content=content,
            section_status=section_status or dict(DEFAULT_SECTION_STATUS),
            evidence_ids=[evidence.evidence_id],
        )
