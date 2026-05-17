"""Skill registry with explicit permission checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from magi_spec.core.errors import PermissionDeniedError
from magi_spec.skills.permissions import AGENT_SKILL_PERMISSIONS


SkillCallable = Callable[..., Any]


@dataclass(slots=True)
class SkillDefinition:
    capability_id: str
    purpose: str
    allowed_agents: set[str]
    input_contract: str
    output_contract: str
    safety_restrictions: str
    artifact_logging_required: bool
    shareable_with_agents: bool
    handler: SkillCallable | None = None


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}

    def register(self, skill: SkillDefinition) -> None:
        self._skills[skill.capability_id] = skill

    def get(self, capability_id: str) -> SkillDefinition:
        return self._skills[capability_id]

    def assert_allowed(self, agent_id: str, capability_id: str) -> None:
        allowed = AGENT_SKILL_PERMISSIONS.get(agent_id, set())
        if capability_id not in allowed:
            raise PermissionDeniedError(
                f"Agent '{agent_id}' is not allowed to use skill '{capability_id}'."
            )

    def execute(self, agent_id: str, capability_id: str, *args: Any, **kwargs: Any) -> Any:
        self.assert_allowed(agent_id, capability_id)
        skill = self.get(capability_id)
        if skill.handler is None:
            raise PermissionDeniedError(f"Skill '{capability_id}' has no executable handler.")
        return skill.handler(*args, **kwargs)

    def to_public_contracts(self) -> list[dict[str, Any]]:
        return [
            {
                "capability_id": skill.capability_id,
                "purpose": skill.purpose,
                "allowed_agents": sorted(skill.allowed_agents),
                "input_contract": skill.input_contract,
                "output_contract": skill.output_contract,
                "safety_restrictions": skill.safety_restrictions,
                "artifact_logging_required": skill.artifact_logging_required,
                "shareable_with_agents": skill.shareable_with_agents,
            }
            for skill in self._skills.values()
        ]


def build_default_skill_registry() -> SkillRegistry:
    registry = SkillRegistry()
    all_skills = {
        skill for permissions in AGENT_SKILL_PERMISSIONS.values() for skill in permissions
    }
    for skill in sorted(all_skills):
        allowed_agents = {
            agent for agent, permissions in AGENT_SKILL_PERMISSIONS.items() if skill in permissions
        }
        registry.register(
            SkillDefinition(
                capability_id=skill,
                purpose=f"Execute the {skill} capability.",
                allowed_agents=allowed_agents,
                input_contract="Structured Python arguments defined by the caller.",
                output_contract="Serializable result or persisted artifact path.",
                safety_restrictions="Must follow MAGI permission and artifact policies.",
                artifact_logging_required=skill
                in {
                    "web_search",
                    "record_evidence",
                    "write_artifact",
                    "execute_command_guarded",
                    "scan_project_folder",
                },
                shareable_with_agents=skill != "execute_command_guarded",
            )
        )
    return registry
