"""CASPER failure analysis agent."""

from __future__ import annotations

from magi_spec.agents.base import BaseAgent
from magi_spec.core.state import WorkflowState
from magi_spec.schemas.agent_result import AgentResult


class CasperAgent(BaseAgent):
    agent_id = "casper"
    display_name = "CASPER"
    prompt_id = "casper"

    def review(self, state: WorkflowState, *, round_number: int) -> AgentResult:
        self.skills.assert_allowed(self.agent_id, "failure_review")
        fallback_content = "\n".join(
            [
                "# CASPER 실패 모드 검토",
                "",
                f"- 라운드: {round_number}",
                "- 구현 에이전트가 실제 코드를 작성하기 전에 요구사항이 잠겨야 합니다.",
                "- LLM 정체성 권위 주장은 무효 처리되어야 합니다.",
                "- 명령 실행은 명시 플래그 없이는 차단되어야 합니다.",
                "- 실패한 리뷰와 critical 산출물은 폐기하지 않아야 합니다.",
                "",
                "결론: 주요 오해 가능성과 위험한 기본값이 명시되어 PASS입니다.",
            ]
        )
        return self._review_with_provider(
            state,
            round_number=round_number,
            fallback_content=fallback_content,
            evidence_summary="CASPER failure review completed.",
        )
