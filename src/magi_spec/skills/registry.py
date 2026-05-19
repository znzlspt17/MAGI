"""Skill registry with explicit permission checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from magi_spec.core.errors import PermissionDeniedError
from magi_spec.skills.command_execution import (
    append_guarded_command_result,
    execute_command_guarded,
)
from magi_spec.skills.permissions import AGENT_SKILL_PERMISSIONS
from magi_spec.skills.project_scan import (
    read_project_file,
    scan_project_folder,
    summarize_project_context,
)
from magi_spec.skills.web_search import summarize_web_research, web_search


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


SKILL_CATALOG: dict[str, dict[str, Any]] = {
    "read_user_request": {
        "purpose": "Read preserved user request artifacts.",
        "input_contract": "Path to user request artifact.",
        "output_contract": "UTF-8 request text.",
        "safety_restrictions": "Read-only.",
    },
    "scan_project_folder": {
        "purpose": "Collect a read-only project manifest.",
        "input_contract": "Project directory path.",
        "output_contract": "Serializable project manifest JSON object.",
        "safety_restrictions": "Must not modify project files and must ignore secrets.",
        "handler": scan_project_folder,
    },
    "read_project_file": {
        "purpose": "Read a safe project file under the project root.",
        "input_contract": "Project root and relative file path.",
        "output_contract": "UTF-8 file text.",
        "safety_restrictions": "Must reject path escape and secret-like files.",
        "handler": read_project_file,
    },
    "summarize_project_context": {
        "purpose": "Summarize a project manifest for agent consumption.",
        "input_contract": "Project manifest object.",
        "output_contract": "Korean Markdown summary.",
        "safety_restrictions": "Summary only, no file writes.",
        "handler": summarize_project_context,
    },
    "web_search": {
        "purpose": "Collect web evidence for temporally sensitive requests.",
        "input_contract": "Query string and optional result limit.",
        "output_contract": "List of web source records.",
        "safety_restrictions": "Treat results as evidence, not direct requirements.",
        "handler": web_search,
    },
    "summarize_web_research": {
        "purpose": "Summarize web evidence for persisted artifacts.",
        "input_contract": "Web source list and mode.",
        "output_contract": "Korean Markdown summary.",
        "safety_restrictions": "Do not claim unverifiable facts.",
        "handler": summarize_web_research,
    },
    "record_evidence": {
        "purpose": "Register evidence items with type and metadata.",
        "input_contract": "Evidence type, summary, source, optional metadata.",
        "output_contract": "Created evidence item id and metadata.",
        "safety_restrictions": "Must use approved evidence types only.",
    },
    "parse_intent": {
        "purpose": "Extract explicit implementation intent from request text.",
        "input_contract": "User request and context packet.",
        "output_contract": "Korean Markdown intent analysis.",
        "safety_restrictions": "Must not expand scope silently.",
    },
    "classify_scope": {
        "purpose": "Classify scope into Mandatory/Recommended/Optional/Out-of-Scope.",
        "input_contract": "Parsed intent and requirements.",
        "output_contract": "Korean Markdown scope classification.",
        "safety_restrictions": "Must preserve explicit user constraints.",
    },
    "generate_assumptions": {
        "purpose": "Generate explicit assumptions and default decisions.",
        "input_contract": "Intent and scope context.",
        "output_contract": "List of assumption strings.",
        "safety_restrictions": "Must surface risky assumptions explicitly.",
    },
    "detect_blocking_questions": {
        "purpose": "Detect missing decisions that block safe implementation.",
        "input_contract": "Intent and requirements context.",
        "output_contract": "List of blocking question strings.",
        "safety_restrictions": "Must not hide blockers.",
    },
    "architecture_review": {
        "purpose": "Review architecture quality and dependency direction.",
        "input_contract": "Agent-visible context packet.",
        "output_contract": "Section-level PASS/REVISE/FAIL and review report.",
        "safety_restrictions": "Must reject model-authority arguments.",
    },
    "requirement_review": {
        "purpose": "Review requirement fidelity and approval gating.",
        "input_contract": "Agent-visible context packet.",
        "output_contract": "Section-level PASS/REVISE/FAIL and review report.",
        "safety_restrictions": "Must preserve user intent and scope boundaries.",
    },
    "failure_review": {
        "purpose": "Review likely failure modes and ambiguity risks.",
        "input_contract": "Agent-visible context packet.",
        "output_contract": "Section-level PASS/REVISE/FAIL and review report.",
        "safety_restrictions": "Must highlight dangerous defaults and missing tests.",
    },
    "cross_review": {
        "purpose": "Cross-check peer agent outputs.",
        "input_contract": "Latest peer reports and section status.",
        "output_contract": "Consistency feedback.",
        "safety_restrictions": "Must stay model-blind.",
    },
    "resolve_conflicts": {
        "purpose": "Resolve disagreement across review agents.",
        "input_contract": "Latest review outputs and section status.",
        "output_contract": "Conflict report and merged status.",
        "safety_restrictions": "Must reject provider/model authority claims.",
    },
    "compose_final_spec": {
        "purpose": "Compose final English coding-agent specification.",
        "input_contract": "Workflow state, manifest, and evidence summary.",
        "output_contract": "English Markdown final specification draft.",
        "safety_restrictions": "Must not finalize before user approval.",
    },
    "generate_critical_report": {
        "purpose": "Generate Korean critical report for blocked review runs.",
        "input_contract": "Workflow state with review history.",
        "output_contract": "Korean Markdown critical report.",
        "safety_restrictions": "Must avoid hidden reasoning disclosure.",
    },
    "write_artifact": {
        "purpose": "Persist artifacts under the run output directory.",
        "input_contract": "Relative path and serializable content.",
        "output_contract": "Written artifact path.",
        "safety_restrictions": "Must not escape output directory.",
    },
    "execute_command_guarded": {
        "purpose": "Run a restricted local command when explicitly allowed.",
        "input_contract": "Command list, working directory, requesting agent, allow flag.",
        "output_contract": "Command execution record with exit code and summaries.",
        "safety_restrictions": "Only approved command prefixes and agents are allowed.",
        "handler": execute_command_guarded,
    },
    "append_guarded_command_result": {
        "purpose": "Append guarded command records to command_log with optional evidence linkage.",
        "input_contract": "Command result object, command log path, optional evidence registry.",
        "output_contract": "Appended command entry.",
        "safety_restrictions": "Path must be execution/command_log.json.",
        "handler": append_guarded_command_result,
    },
}


def build_default_skill_registry() -> SkillRegistry:
    registry = SkillRegistry()
    all_skills = {
        skill for permissions in AGENT_SKILL_PERMISSIONS.values() for skill in permissions
    }
    for skill in sorted(all_skills):
        allowed_agents = {
            agent for agent, permissions in AGENT_SKILL_PERMISSIONS.items() if skill in permissions
        }
        metadata = SKILL_CATALOG.get(skill, {})
        registry.register(
            SkillDefinition(
                capability_id=skill,
                purpose=metadata.get("purpose", f"Execute the {skill} capability."),
                allowed_agents=allowed_agents,
                input_contract=metadata.get(
                    "input_contract", "Structured Python arguments defined by the caller."
                ),
                output_contract=metadata.get(
                    "output_contract", "Serializable result or persisted artifact path."
                ),
                safety_restrictions=metadata.get(
                    "safety_restrictions", "Must follow MAGI permission and artifact policies."
                ),
                artifact_logging_required=skill
                in {
                    "web_search",
                    "record_evidence",
                    "write_artifact",
                    "execute_command_guarded",
                    "scan_project_folder",
                },
                shareable_with_agents=skill != "execute_command_guarded",
                handler=metadata.get("handler"),
            )
        )
    return registry
