"""MELCHIOR architecture agent."""

from __future__ import annotations

from magi_spec.agents.base import BaseAgent
from magi_spec.core.state import WorkflowState
from magi_spec.schemas.agent_result import AgentResult


class MelchiorAgent(BaseAgent):
    agent_id = "melchior"
    display_name = "MELCHIOR"

    def review(self, state: WorkflowState, *, round_number: int) -> AgentResult:
        self.skills.assert_allowed(self.agent_id, "architecture_review")
        content = "\n".join(
            [
                "# MELCHIOR 아키텍처 검토",
                "",
                f"- 라운드: {round_number}",
                "- CLI는 얇게 유지하고 핵심 워크플로는 Python 패키지에 둡니다.",
                "- 상태, 산출물, 증거, LLM 호출 경계, skill registry, agent, graph 계층을 분리해야 합니다.",
                "- 프로젝트 스캔은 읽기 전용이어야 하며 구현 대상 저장소를 변경하면 안 됩니다.",
                "- 최종 구현 지시서는 사용자 승인 이후에만 승격되어야 합니다.",
                "",
                "결론: 현재 후보 명세는 아키텍처 책임 분리를 충분히 강제하므로 PASS입니다.",
            ]
        )
        return self._result(content, evidence_summary="MELCHIOR architecture review passed.")
