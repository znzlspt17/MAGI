"""Evidence registry used by analysis, reviews, and final specs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


VALID_EVIDENCE_TYPES = {
    "USER_REQUEST",
    "PROJECT_FILE",
    "WEB_SOURCE",
    "COMMAND_RESULT",
    "AGENT_ASSUMPTION",
    "AGENT_REVIEW",
}


@dataclass(slots=True)
class EvidenceItem:
    evidence_id: str
    evidence_type: str
    summary: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type,
            "summary": self.summary,
            "source": self.source,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


class EvidenceRegistry:
    def __init__(self, items: list[EvidenceItem] | None = None) -> None:
        self.items = items or []

    def add(
        self,
        evidence_type: str,
        summary: str,
        source: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> EvidenceItem:
        if evidence_type not in VALID_EVIDENCE_TYPES:
            raise ValueError(f"Unsupported evidence type: {evidence_type}")
        item = EvidenceItem(
            evidence_id=f"ev_{uuid4().hex[:12]}",
            evidence_type=evidence_type,
            summary=summary,
            source=source,
            metadata=metadata or {},
        )
        self.items.append(item)
        return item

    def to_dict(self) -> dict[str, Any]:
        return {"items": [item.to_dict() for item in self.items]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceRegistry":
        return cls(
            [
                EvidenceItem(
                    evidence_id=item["evidence_id"],
                    evidence_type=item["evidence_type"],
                    summary=item["summary"],
                    source=item["source"],
                    metadata=item.get("metadata", {}),
                    created_at=item.get("created_at", ""),
                )
                for item in data.get("items", [])
            ]
        )
