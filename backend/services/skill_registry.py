"""v2 단계의 capability 권한 검사."""

from backend.errors import PermissionDeniedError
from backend.infrastructure.permissions import AGENT_SKILL_PERMISSIONS


class SkillRegistry:
    def assert_allowed(self, agent_id: str, capability_id: str) -> None:
        if capability_id not in AGENT_SKILL_PERMISSIONS.get(agent_id, set()):
            raise PermissionDeniedError(
                f"Agent '{agent_id}' is not allowed to use skill '{capability_id}'."
            )


def build_default_skill_registry() -> SkillRegistry:
    return SkillRegistry()
