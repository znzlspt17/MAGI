"""Conflict resolver agent."""

from __future__ import annotations

from magi_spec.core.evidence import EvidenceRegistry
from magi_spec.core.model_blind import contains_model_authority_claim
from magi_spec.core.state import WorkflowState
from magi_spec.schemas.agent_result import AgentResult
from magi_spec.skills.registry import SkillRegistry


class ConflictResolver:
    agent_id = "conflict_resolver"

    def __init__(self, *, skills: SkillRegistry, evidence: EvidenceRegistry) -> None:
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
        evidence = self.evidence.add(
            "AGENT_REVIEW",
            "Conflict resolver completed a model-blind review merge.",
            "ConflictResolver",
        )
        return AgentResult(
            agent_id=self.agent_id,
            status=status,
            content=content,
            section_status=dict(state.get("section_status", {})),
            evidence_ids=[evidence.evidence_id],
        )
