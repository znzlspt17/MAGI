"""Structured issue packet schema for v2 Checklist Critic output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


VALID_SEVERITY = {"blocking", "major", "minor"}
VALID_ISSUE_STATUS = {"open", "resolved", "deferred"}


@dataclass(slots=True)
class IssueEvidence:
    source: str
    quote: str

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "quote": self.quote}

    @classmethod
    def from_dict(cls, data: Any) -> "IssueEvidence":
        if not isinstance(data, dict):
            return cls(source="unknown", quote="")
        return cls(
            source=str(data.get("source", "unknown")),
            quote=str(data.get("quote", "")),
        )


@dataclass(slots=True)
class IssuePacket:
    issue_id: str
    section: str
    severity: str  # blocking|major|minor
    blocking: bool
    checklist_id: str
    problem: str
    required_change: str
    evidence: list[IssueEvidence] = field(default_factory=list)
    suggested_patch: str | None = None
    status: str = "open"  # open|resolved|deferred

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "section": self.section,
            "severity": self.severity,
            "blocking": self.blocking,
            "checklist_id": self.checklist_id,
            "problem": self.problem,
            "required_change": self.required_change,
            "evidence": [e.to_dict() for e in self.evidence],
            "suggested_patch": self.suggested_patch,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, fallback_id: str = "ISSUE-UNK") -> "IssuePacket":
        raw_severity = normalize_severity(data.get("severity"), default="major")
        # Enforce: blocking iff severity=="blocking"
        blocking = raw_severity == "blocking"
        raw_status = str(data.get("status", "open")).lower()
        status = raw_status if raw_status in VALID_ISSUE_STATUS else "open"
        evidence_raw = data.get("evidence", [])
        evidence = (
            [IssueEvidence.from_dict(e) for e in evidence_raw]
            if isinstance(evidence_raw, list)
            else []
        )
        return cls(
            issue_id=str(data.get("issue_id", fallback_id)),
            section=str(data.get("section", "unknown")),
            severity=raw_severity,
            blocking=blocking,
            checklist_id=str(data.get("checklist_id", fallback_id)),
            problem=str(data.get("problem", "")),
            required_change=str(data.get("required_change", "")),
            evidence=evidence,
            suggested_patch=data.get("suggested_patch") or None,
            status=status,
        )


def normalize_severity(value: Any, *, default: str = "major") -> str:
    s = str(value or default).lower().strip()
    return s if s in VALID_SEVERITY else default


def parse_issue_list(data: Any) -> list[IssuePacket]:
    """Parse a provider response into IssuePacket list.

    Accepts dict with "issues" key, or a raw list.
    Returns empty list if data is missing or malformed (relies on deterministic
    checks as the authoritative source of blocking issues).
    """
    if data is None:
        return []
    if isinstance(data, dict):
        raw = data.get("issues", [])
    elif isinstance(data, list):
        raw = data
    else:
        return []
    if not isinstance(raw, list):
        return []
    result: list[IssuePacket] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        try:
            result.append(IssuePacket.from_dict(item, fallback_id=f"ISSUE-{i:03d}"))
        except Exception:
            continue
    return result


def count_unresolved_blocking(issues: list[IssuePacket]) -> int:
    return sum(1 for i in issues if i.blocking and i.status != "resolved")


def merge_issue_lists(
    base: list[IssuePacket],
    additional: list[IssuePacket],
) -> list[IssuePacket]:
    """Merge two lists, deduplicating by checklist_id (base wins on conflict)."""
    seen = {i.checklist_id for i in base}
    merged = list(base)
    for issue in additional:
        if issue.checklist_id not in seen:
            merged.append(issue)
            seen.add(issue.checklist_id)
    return merged
