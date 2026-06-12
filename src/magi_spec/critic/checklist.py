"""Checklist definitions and deterministic checks for v2 Checklist Critic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from magi_spec.compiler.spec_compiler import REQUIRED_FINAL_SPEC_HEADINGS
from magi_spec.schemas.issue_packet import IssuePacket
from magi_spec.schemas.requirement_lock import RequirementLockSheet


@dataclass(slots=True)
class ChecklistItem:
    checklist_id: str
    section: str
    severity: str  # blocking|major|minor
    description: str


CHECKLIST: list[ChecklistItem] = [
    ChecklistItem(
        "SEC-REQUIRED-001",
        "structure",
        "blocking",
        "필수 26개 heading 전부 존재",
    ),
    ChecklistItem(
        "SCOPE-NONSCOPE-001",
        "scope",
        "blocking",
        "Out of Scope (### 4.2 Out of Scope) 섹션이 비어있지 않음",
    ),
    ChecklistItem(
        "FORBIDDEN-001",
        "forbidden",
        "blocking",
        "## 10. Forbidden Behaviors 섹션이 비어있지 않음",
    ),
    ChecklistItem(
        "AC-001",
        "acceptance",
        "blocking",
        "## 20. Acceptance Criteria 섹션이 비어있지 않음",
    ),
    ChecklistItem(
        "TEST-001",
        "test_plan",
        "blocking",
        "## 21. Test Plan 섹션이 비어있지 않음",
    ),
    ChecklistItem(
        "UNRESOLVED-Q-001",
        "intent",
        "blocking",
        "미해결 blocking question이 0개여야 함",
    ),
    ChecklistItem(
        "AMBIG-001",
        "requirements",
        "major",
        "모호한 표현(robust, good, appropriate, 적절히)이 Mandatory Requirements에 없음",
    ),
    ChecklistItem(
        "LOCK-COVER-001",
        "requirements",
        "major",
        "lock sheet의 mandatory requirement가 최종 명세에 등장",
    ),
]

_AMBIGUOUS_WORDS = {
    "robust", "good", "appropriate", "suitable", "reasonable",
    "proper", "adequate", "optimal", "nice", "elegant",
    "적절히", "좋은", "충분한", "올바른", "최적",
}


def run_deterministic_checks(
    spec_md: str,
    sheet: RequirementLockSheet,
) -> list[IssuePacket]:
    """Run deterministic (LLM-free) checks on spec_md against sheet.

    Returns a list of IssuePacket for violations found.
    """
    issues: list[IssuePacket] = []

    # SEC-REQUIRED-001: all 26 headings present
    missing_headings = [h for h in REQUIRED_FINAL_SPEC_HEADINGS if h not in spec_md]
    if missing_headings:
        issues.append(IssuePacket(
            issue_id="SEC-REQUIRED-001",
            section="structure",
            severity="blocking",
            blocking=True,
            checklist_id="SEC-REQUIRED-001",
            problem=f"Missing required headings: {missing_headings[:5]}",
            required_change="Add all required headings in order.",
        ))

    # SCOPE-NONSCOPE-001: Out of Scope not empty
    oos_heading = "### 4.2 Out of Scope"
    if oos_heading in spec_md:
        oos_idx = spec_md.index(oos_heading) + len(oos_heading)
        # Find next heading
        next_heading_idx = _next_heading_idx(spec_md, oos_idx)
        oos_content = spec_md[oos_idx:next_heading_idx].strip()
        if not oos_content or oos_content in ("-", "—", "N/A"):
            issues.append(IssuePacket(
                issue_id="SCOPE-NONSCOPE-001",
                section="scope",
                severity="blocking",
                blocking=True,
                checklist_id="SCOPE-NONSCOPE-001",
                problem="Out of Scope section is empty.",
                required_change="List at least one explicit out-of-scope item.",
            ))

    # FORBIDDEN-001: Forbidden Behaviors not empty
    fb_heading = "## 10. Forbidden Behaviors"
    if fb_heading in spec_md:
        fb_idx = spec_md.index(fb_heading) + len(fb_heading)
        next_idx = _next_heading_idx(spec_md, fb_idx)
        fb_content = spec_md[fb_idx:next_idx].strip()
        if not fb_content or fb_content in ("-", "—", "N/A"):
            issues.append(IssuePacket(
                issue_id="FORBIDDEN-001",
                section="forbidden",
                severity="blocking",
                blocking=True,
                checklist_id="FORBIDDEN-001",
                problem="Forbidden Behaviors section is empty.",
                required_change="List at least one explicit forbidden behavior.",
            ))

    # AC-001: Acceptance Criteria not empty
    ac_heading = "## 20. Acceptance Criteria"
    if ac_heading in spec_md:
        ac_idx = spec_md.index(ac_heading) + len(ac_heading)
        next_idx = _next_heading_idx(spec_md, ac_idx)
        ac_content = spec_md[ac_idx:next_idx].strip()
        if not ac_content or ac_content in ("-", "—", "N/A"):
            issues.append(IssuePacket(
                issue_id="AC-001",
                section="acceptance",
                severity="blocking",
                blocking=True,
                checklist_id="AC-001",
                problem="Acceptance Criteria section is empty.",
                required_change="Provide at least one verifiable acceptance criterion.",
            ))

    # TEST-001: Test Plan not empty
    tp_heading = "## 21. Test Plan"
    if tp_heading in spec_md:
        tp_idx = spec_md.index(tp_heading) + len(tp_heading)
        next_idx = _next_heading_idx(spec_md, tp_idx)
        tp_content = spec_md[tp_idx:next_idx].strip()
        if not tp_content or tp_content in ("-", "—", "N/A"):
            issues.append(IssuePacket(
                issue_id="TEST-001",
                section="test_plan",
                severity="blocking",
                blocking=True,
                checklist_id="TEST-001",
                problem="Test Plan section is empty.",
                required_change="Provide at least one test strategy.",
            ))

    # UNRESOLVED-Q-001: no unresolved blocking questions
    if sheet.unresolved_questions:
        issues.append(IssuePacket(
            issue_id="UNRESOLVED-Q-001",
            section="intent",
            severity="blocking",
            blocking=True,
            checklist_id="UNRESOLVED-Q-001",
            problem=f"Unresolved blocking questions: {sheet.unresolved_questions[:3]}",
            required_change="Resolve all blocking questions before finalising the spec.",
        ))

    # AMBIG-001: no ambiguous words in Mandatory Requirements (major, non-blocking)
    req_heading = "## 7. Mandatory Requirements"
    if req_heading in spec_md:
        req_idx = spec_md.index(req_heading) + len(req_heading)
        next_idx = _next_heading_idx(spec_md, req_idx)
        req_text = spec_md[req_idx:next_idx].lower()
        found_ambig = [w for w in _AMBIGUOUS_WORDS if w.lower() in req_text]
        if found_ambig:
            issues.append(IssuePacket(
                issue_id="AMBIG-001",
                section="requirements",
                severity="major",
                blocking=False,
                checklist_id="AMBIG-001",
                problem=f"Ambiguous words in Mandatory Requirements: {found_ambig}",
                required_change="Replace ambiguous words with measurable, verifiable language.",
            ))

    # LOCK-COVER-001: mandatory requirements appear in spec (major, non-blocking)
    for req in sheet.mandatory_requirements:
        key_words = [w for w in req.text.split() if len(w) > 4]
        if key_words:
            first_word = key_words[0].lower().rstrip(".,;:")
            if first_word and first_word not in spec_md.lower():
                issues.append(IssuePacket(
                    issue_id=f"LOCK-COVER-{req.id}",
                    section="requirements",
                    severity="major",
                    blocking=False,
                    checklist_id="LOCK-COVER-001",
                    problem=f"Mandatory requirement [{req.id}] may not be reflected in spec.",
                    required_change=f"Ensure the spec addresses: {req.text}",
                ))
                break  # One issue per batch is enough

    return issues


def _next_heading_idx(text: str, start: int) -> int:
    """Find the start index of the next Markdown heading after `start`."""
    pos = start
    while pos < len(text):
        newline = text.find("\n#", pos)
        if newline == -1:
            return len(text)
        return newline + 1  # position of '#'
    return len(text)
