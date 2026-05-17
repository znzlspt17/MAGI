"""Agent result schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class AgentResult:
    agent_id: str
    status: str
    content: str
    section_status: dict[str, str]
    evidence_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "status": self.status,
            "content": self.content,
            "section_status": self.section_status,
            "evidence_ids": self.evidence_ids,
            "created_at": self.created_at,
        }
