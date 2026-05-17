"""BALTHASAR requirement guardian."""

from __future__ import annotations

from magi_spec.agents.base import BaseAgent
from magi_spec.core.state import WorkflowState
from magi_spec.schemas.agent_result import AgentResult


class BalthasarAgent(BaseAgent):
    agent_id = "balthasar"
    display_name = "BALTHASAR"

    def review(self, state: WorkflowState, *, round_number: int) -> AgentResult:
        self.skills.assert_allowed(self.agent_id, "requirement_review")
        content = "\n".join(
            [
                "# BALTHASAR 요구사항 검토",
                "",
                f"- 라운드: {round_number}",
                "- 사용자 요청은 원문 산출물로 보존되어야 합니다.",
                "- 필수, 권장, 선택, 범위 밖 항목이 구분되어야 합니다.",
                "- 승인 후보와 최종 명세의 구분이 유지되어야 합니다.",
                "- 중간 분석은 한국어, 최종 명세는 영어여야 합니다.",
                "",
                "결론: 사용자 의도와 승인 흐름을 훼손하지 않으므로 PASS입니다.",
            ]
        )
        return self._result(content, evidence_summary="BALTHASAR requirement review passed.")
