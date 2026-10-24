"""검증된 실행 결과로 만드는 결정적 검토 실패 보고서."""

from backend.models import WorkflowState
from backend.services.skill_registry import SkillRegistry


class CriticalReporter:
    agent_id = "critical_reporter"

    def __init__(self, *, skills: SkillRegistry) -> None:
        self.skills = skills

    def generate(self, state: WorkflowState) -> str:
        self.skills.assert_allowed(self.agent_id, "generate_critical_report")
        from backend.services.review_resolution import failure_report
        return failure_report(state)
