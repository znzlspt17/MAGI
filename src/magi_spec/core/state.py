"""State model for persisted MAGI runs."""

from __future__ import annotations

import dataclasses
from dataclasses import asdict, dataclass, field
from typing import Any, TypedDict


STATUS_DRAFT = "DRAFT"
STATUS_ANALYZING = "ANALYZING"
STATUS_RESEARCHING = "RESEARCHING"
STATUS_COMPILING = "COMPILING"
STATUS_CRITIQUING = "CRITIQUING"
STATUS_NEEDS_USER_INPUT = "NEEDS_USER_INPUT"
STATUS_PASS_PENDING_USER_APPROVAL = "PASS_PENDING_USER_APPROVAL"
STATUS_APPROVED = "APPROVED"
STATUS_FINALIZED = "FINALIZED"
STATUS_CRITICAL_BLOCKED = "CRITICAL_BLOCKED"
STATUS_REJECTED_BY_USER = "REJECTED_BY_USER"


class WorkflowState(TypedDict, total=False):
    """LangGraph-visible state shape."""

    run_id: str
    status: str
    user_request: str
    input_source: str
    project_dir: str | None
    output_dir: str
    web_search_mode: str
    command_execution_allowed: bool
    # interview stage
    request_type: str
    assumptions: list[str]
    blocking_questions: list[str]
    _interview_direction_changing: bool
    # requirement lock stage
    requirement_lock: str
    requirement_lock_sheet: dict[str, Any] | None
    # critic stage
    structured_issues: list[dict[str, Any]]
    critic_pass_count: int
    max_critic_passes: int
    # artifact tracking
    evidence_registry_path: str
    project_manifest_path: str | None
    web_sources_path: str | None
    command_log_path: str | None
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
    web_search_mode: str = "auto"
    command_execution_allowed: bool = False
    # interview stage
    request_type: str = ""
    assumptions: list[str] = field(default_factory=list)
    blocking_questions: list[str] = field(default_factory=list)
    # requirement lock stage
    requirement_lock: str = ""
    requirement_lock_sheet: dict[str, Any] | None = field(default=None)
    # critic stage
    structured_issues: list[dict[str, Any]] = field(default_factory=list)
    critic_pass_count: int = 0
    max_critic_passes: int = 2
    # artifact tracking
    evidence_registry_path: str = ""
    project_manifest_path: str | None = None
    web_sources_path: str | None = None
    command_log_path: str | None = None
    approval_candidate_spec: str | None = None
    final_agent_spec: str | None = None
    critical_report: str | None = None
    user_approval_status: str = "PENDING"
    created_artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MagiState":
        valid_fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def to_workflow_state(self) -> WorkflowState:
        return self.to_dict()  # type: ignore[return-value]

    @classmethod
    def from_workflow_state(cls, data: WorkflowState) -> "MagiState":
        return cls.from_dict(dict(data))

        # Only pass keys that exist in the dataclass to allow loading older state files.
        import dataclasses
        valid_fields = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    def to_workflow_state(self) -> WorkflowState:
        return self.to_dict()  # type: ignore[return-value]

    @classmethod
    def from_workflow_state(cls, data: WorkflowState) -> "MagiState":
        return cls.from_dict(dict(data))
