"""Conflict resolver agent."""

from __future__ import annotations

from magi_spec.agents.base import DEFAULT_SECTION_STATUS
from magi_spec.core.agent_context import build_agent_visible_context
from magi_spec.core.config import MagiConfig
from magi_spec.core.evidence import EvidenceRegistry
from magi_spec.core.model_blind import contains_model_authority_claim
from magi_spec.core.prompts import load_prompt
from magi_spec.core.provider_output import extract_json_object
from magi_spec.core.state import WorkflowState
from magi_spec.providers.base import ProviderFactory
from magi_spec.schemas.agent_result import AgentResult
from magi_spec.schemas.provider_packets import ReviewPacket, normalize_review_status
from magi_spec.skills.registry import SkillRegistry


class ConflictResolver:
    agent_id = "conflict_resolver"

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

    def resolve(self, state: WorkflowState, *, round_number: int) -> AgentResult:
        self.skills.assert_allowed(self.agent_id, "resolve_conflicts")
        statuses = []
        for key in ("melchior_outputs", "balthasar_outputs", "casper_outputs"):
            if state.get(key):
                statuses.append(state[key][-1].get("status", "UNKNOWN"))  # type: ignore[index]
        latest_outputs = [
            state[key][-1]
            for key in ("melchior_outputs", "balthasar_outputs", "casper_outputs")
            if state.get(key)
        ]
        authority_claim_found = any(
            contains_model_authority_claim(str(output.get("content", "")))
            for output in latest_outputs
        )
        status = (
            "PASS"
            if statuses and all(item == "PASS" for item in statuses) and not authority_claim_found
            else "REVISE"
        )
        content = "\n".join(
            [
                "# 충돌 해결 보고서",
                "",
                f"- 라운드: {round_number}",
                f"- 검토 상태: {', '.join(statuses) if statuses else '없음'}",
                "- 실행 라우팅 식별 정보는 검토 자료에 포함되지 않았습니다.",
                f"- LLM 정체성 권위 주장 발견 여부: {'있음' if authority_claim_found else '없음'}",
                "- 현재 라운드에서 해결 불가능한 요구사항 충돌은 발견되지 않았습니다.",
            ]
        )
        provider_status, provider_content, provider_sections = self._provider_resolution(
            state,
            round_number=round_number,
            fallback_status=status,
            fallback_content=content,
            fallback_sections=dict(state.get("section_status", {})),
        )
        status = provider_status
        content = provider_content
        section_status = provider_sections
        if authority_claim_found or contains_model_authority_claim(content):
            status = "REVISE"
            section_status = {
                section: "FAIL"
                for section in (state.get("section_status", {}) or DEFAULT_SECTION_STATUS)
            }
            content = "\n".join(
                [
                    "# 충돌 해결 보고서",
                    "",
                    f"- 라운드: {round_number}",
                    "- 모델 또는 제공자 권위 주장이 발견되어 현재 라운드는 통과할 수 없습니다.",
                    "- 유효한 근거는 요구사항, 증거, 테스트 결과, 아키텍처 제약, 실패 모드여야 합니다.",
                ]
            )
        evidence = self.evidence.add(
            "AGENT_REVIEW",
            "Conflict resolver completed a model-blind review merge.",
            "ConflictResolver",
        )
        return AgentResult(
            agent_id=self.agent_id,
            status=status,
            content=content,
            section_status=section_status,
            evidence_ids=[evidence.evidence_id],
        )

    def _provider_resolution(
        self,
        state: WorkflowState,
        *,
        round_number: int,
        fallback_status: str,
        fallback_content: str,
        fallback_sections: dict[str, str],
    ) -> tuple[str, str, dict[str, str]]:
        route = self.config.model_routing[self.agent_id]
        provider = self.providers.get(route.provider)
        prompt = "\n\n".join(
            [
                load_prompt("conflict_resolver"),
                build_agent_visible_context(
                    state,
                    agent_id=self.agent_id,
                    round_number=round_number,
                ),
                "Return only JSON with keys: status, section_status, content.",
                "status must be PASS, REVISE, or FAIL. content must be Korean.",
            ]
        )
        raw_output = provider.complete(
            [{"role": "user", "content": prompt}],
            model=route.model,
            temperature=0,
        )
        parsed = extract_json_object(raw_output)
        packet = ReviewPacket.from_provider_dict(
            parsed,
            fallback_status=fallback_status,
            fallback_content=fallback_content,
            fallback_sections=fallback_sections,
            allow_static_fallback=True,
            malformed_error_title="# 충돌 해결 구조화 응답 오류",
        )
        sections = dict(fallback_sections)
        severity = {"PASS": 0, "REVISE": 1, "FAIL": 2}
        for section, status in packet.section_status.items():
            normalized = normalize_review_status(status, default="REVISE")
            if severity[normalized] > severity.get(sections.get(section, "PASS"), 0):
                sections[section] = normalized
        return (packet.status, packet.content, sections)
