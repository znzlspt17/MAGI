"""State model for persisted MAGI runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, TypedDict


STATUS_DRAFT = "DRAFT"
STATUS_ANALYZING = "ANALYZING"
STATUS_RESEARCHING = "RESEARCHING"
STATUS_REVIEWING = "REVIEWING"
STATUS_REVISING = "REVISING"
STATUS_PASS_PENDING_USER_APPROVAL = "PASS_PENDING_USER_APPROVAL"
STATUS_APPROVED = "APPROVED"
STATUS_FINALIZED = "FINALIZED"
STATUS_CRITICAL_BLOCKED = "CRITICAL_BLOCKED"
STATUS_REJECTED_BY_USER = "REJECTED_BY_USER"


class WorkflowState(TypedDict, total=False):
    """LangGraph-visible state shape.

    Provider/model routing is intentionally absent from this schema so it does
    not leak into agent-visible packets.
    """

    run_id: str
    status: str
    user_request: str
    input_source: str
    project_dir: str | None
    output_dir: str
    current_round: int
    min_rounds: int
    max_rounds: int
    web_search_mode: str
    command_execution_allowed: bool
    intent_parse: str
    requirement_lock: str
    scope_classification: str
    assumptions: list[str]
    blocking_questions: list[str]
    evidence_registry_path: str
    project_manifest_path: str | None
    web_sources_path: str | None
    command_log_path: str | None
    melchior_outputs: list[dict[str, Any]]
    balthasar_outputs: list[dict[str, Any]]
    casper_outputs: list[dict[str, Any]]
    conflict_reports: list[dict[str, Any]]
    section_status: dict[str, str]
    stagnant_rounds: int
    approval_candidate_spec: str | None
    final_agent_spec: str | None
    critical_report: str | None
    user_approval_status: str
    created_artifacts: list[str]


@dataclass(slots=True)
class MagiState:
    run_id: str
    status: str
    user_request: str
    input_source: str
    project_dir: str | None
    output_dir: str
    current_round: int = 0
    min_rounds: int = 3
    max_rounds: int = 10
    web_search_mode: str = "auto"
    command_execution_allowed: bool = False
    intent_parse: str = ""
    requirement_lock: str = ""
    scope_classification: str = ""
    assumptions: list[str] = field(default_factory=list)
    blocking_questions: list[str] = field(default_factory=list)
    evidence_registry_path: str = ""
    project_manifest_path: str | None = None
    web_sources_path: str | None = None
    command_log_path: str | None = None
    melchior_outputs: list[dict[str, Any]] = field(default_factory=list)
    balthasar_outputs: list[dict[str, Any]] = field(default_factory=list)
    casper_outputs: list[dict[str, Any]] = field(default_factory=list)
    conflict_reports: list[dict[str, Any]] = field(default_factory=list)
    section_status: dict[str, str] = field(default_factory=dict)
    stagnant_rounds: int = 0
    approval_candidate_spec: str | None = None
    final_agent_spec: str | None = None
    critical_report: str | None = None
    user_approval_status: str = "PENDING"
    created_artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MagiState":
        return cls(**data)

    def to_workflow_state(self) -> WorkflowState:
        return self.to_dict()  # type: ignore[return-value]

    @classmethod
    def from_workflow_state(cls, data: WorkflowState) -> "MagiState":
        return cls.from_dict(dict(data))
