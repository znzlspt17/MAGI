"""Checklist definitions and deterministic checks for v2 Checklist Critic."""

from __future__ import annotations

import re

from backend.models import ChecklistItem
from backend.models import IssueEvidence
from backend.models import IssuePacket
from backend.models import RequirementLockSheet
from backend.services.spec_compiler import REQUIRED_FINAL_SPEC_HEADINGS


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
        "AC-QUALITY-001",
        "acceptance",
        "major",
        "Acceptance Criteria에 Final spec includes... 같은 자리표시자가 없음",
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
        "minor",
        "잠금된 모호한 표현은 관찰 가능한 기준과 테스트로 보강됨",
    ),
    ChecklistItem(
        "LOCK-COVER-001",
        "requirements",
        "major",
        "lock sheet의 mandatory requirement가 최종 명세에 등장",
    ),
]

_AMBIGUOUS_WORDS = {
    "robust",
    "good",
    "appropriate",
    "suitable",
    "reasonable",
    "proper",
    "adequate",
    "optimal",
    "nice",
    "elegant",
    "적절히",
    "좋은",
    "충분한",
    "올바른",
    "최적",
}

_PLACEHOLDER_ACCEPTANCE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\d+[.)]\s*)?final spec includes(?:\s*(?:\.\.\.|…|\.))?\s*$",
    re.IGNORECASE,
)
_GENERIC_COMPLETION_ACCEPTANCE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\d+[.)]\s*)?final spec includes "
    r"(?=[^.]*\bscope\b)(?=[^.]*\bforbidden behaviors\b)"
    r"(?=[^.]*\bacceptance criteria\b)(?=[^.]*\btest plan\b)[^.]+\.?\s*$",
    re.IGNORECASE,
)


def run_deterministic_checks(
    spec_md: str,
    sheet: RequirementLockSheet,
) -> list[IssuePacket]:
    """Run deterministic (LLM-free) checks on spec_md against sheet.

    Returns a list of IssuePacket for violations found.
    """
    issues: list[IssuePacket] = []
    # 코드 블록 속 예시 heading/ID는 명세 본문으로 취급하지 않는다. 길이는
    # 유지해 아래의 위치 기반 섹션 추출이 원본과 같은 오프셋을 사용하게 한다.
    visible_spec = _mask_fenced_code(spec_md)

    # SEC-REQUIRED-001: all 26 headings present
    missing_headings = [
        heading
        for heading in REQUIRED_FINAL_SPEC_HEADINGS
        if _heading_position(visible_spec, heading) is None
    ]
    if missing_headings:
        issues.append(
            IssuePacket(
                issue_id="SEC-REQUIRED-001",
                section="structure",
                severity="blocking",
                blocking=True,
                checklist_id="SEC-REQUIRED-001",
                problem=f"Missing required headings: {missing_headings[:5]}",
                required_change="Add all required headings in order.",
            )
        )
    elif not _headings_in_required_order(visible_spec):
        issues.append(
            IssuePacket(
                issue_id="SEC-REQUIRED-ORDER-001",
                section="structure",
                severity="blocking",
                blocking=True,
                checklist_id="SEC-REQUIRED-ORDER-001",
                problem="Required headings are present but not in the required order.",
                required_change="Restore all required headings in the documented order.",
            )
        )

    # SCOPE-NONSCOPE-001: Out of Scope not empty
    oos_heading = "### 4.2 Out of Scope"
    oos_position = _heading_position(visible_spec, oos_heading)
    if oos_position is not None:
        oos_idx = oos_position + len(oos_heading)
        # Find next heading
        next_heading_idx = _next_heading_idx(visible_spec, oos_idx)
        oos_content = visible_spec[oos_idx:next_heading_idx].strip()
        if not oos_content or oos_content in ("-", "—", "N/A"):
            issues.append(
                IssuePacket(
                    issue_id="SCOPE-NONSCOPE-001",
                    section="scope",
                    severity="blocking",
                    blocking=True,
                    checklist_id="SCOPE-NONSCOPE-001",
                    problem="Out of Scope section is empty.",
                    required_change="List at least one explicit out-of-scope item.",
                )
            )

    # FORBIDDEN-001: Forbidden Behaviors not empty
    fb_heading = "## 10. Forbidden Behaviors"
    fb_position = _heading_position(visible_spec, fb_heading)
    if fb_position is not None:
        fb_idx = fb_position + len(fb_heading)
        next_idx = _next_heading_idx(visible_spec, fb_idx)
        fb_content = visible_spec[fb_idx:next_idx].strip()
        if not fb_content or fb_content in ("-", "—", "N/A"):
            issues.append(
                IssuePacket(
                    issue_id="FORBIDDEN-001",
                    section="forbidden",
                    severity="blocking",
                    blocking=True,
                    checklist_id="FORBIDDEN-001",
                    problem="Forbidden Behaviors section is empty.",
                    required_change="List at least one explicit forbidden behavior.",
                )
            )

    # AC-001: Acceptance Criteria not empty
    ac_heading = "## 20. Acceptance Criteria"
    ac_position = _heading_position(visible_spec, ac_heading)
    if ac_position is not None:
        ac_idx = ac_position + len(ac_heading)
        next_idx = _next_heading_idx(visible_spec, ac_idx)
        ac_content = visible_spec[ac_idx:next_idx].strip()
        if not ac_content or ac_content in ("-", "—", "N/A"):
            issues.append(
                IssuePacket(
                    issue_id="AC-001",
                    section="acceptance",
                    severity="blocking",
                    blocking=True,
                    checklist_id="AC-001",
                    problem="Acceptance Criteria section is empty.",
                    required_change="Provide at least one verifiable acceptance criterion.",
                )
            )
        else:
            acceptance_lines = [line for line in ac_content.splitlines() if line.strip()]
            placeholder_lines = [
                line
                for line in acceptance_lines
                if _PLACEHOLDER_ACCEPTANCE.match(line)
                or _GENERIC_COMPLETION_ACCEPTANCE.match(line)
            ]
            if placeholder_lines:
                only_placeholders = len(placeholder_lines) == len(acceptance_lines)
                severity = "major" if only_placeholders else "minor"
                required_change = (
                    "Replace the placeholder with observable behavior, expected result, "
                    "and a verification method."
                    if only_placeholders
                    else "Remove the redundant completion-summary placeholder."
                )
                issues.append(
                    IssuePacket(
                        issue_id="AC-QUALITY-001",
                        section="acceptance",
                        severity=severity,
                        blocking=False,
                        checklist_id="AC-QUALITY-001",
                        problem=(
                            "Acceptance Criteria contains a generic final-spec completion "
                            "placeholder."
                        ),
                        required_change=required_change,
                    )
                )

    # TEST-001: Test Plan not empty
    tp_heading = "## 21. Test Plan"
    tp_position = _heading_position(visible_spec, tp_heading)
    if tp_position is not None:
        tp_idx = tp_position + len(tp_heading)
        next_idx = _next_heading_idx(visible_spec, tp_idx)
        tp_content = visible_spec[tp_idx:next_idx].strip()
        if not tp_content or tp_content in ("-", "—", "N/A"):
            issues.append(
                IssuePacket(
                    issue_id="TEST-001",
                    section="test_plan",
                    severity="blocking",
                    blocking=True,
                    checklist_id="TEST-001",
                    problem="Test Plan section is empty.",
                    required_change="Provide at least one test strategy.",
                )
            )

    # UNRESOLVED-Q-001: no unresolved blocking questions
    if sheet.unresolved_questions:
        issues.append(
            IssuePacket(
                issue_id="UNRESOLVED-Q-001",
                section="intent",
                severity="blocking",
                blocking=True,
                checklist_id="UNRESOLVED-Q-001",
                problem=f"Unresolved blocking questions: {sheet.unresolved_questions[:3]}",
                required_change="Resolve all blocking questions before finalising the spec.",
            )
        )

    # AMBIG-001: locked wording is preserved; flag it only as an operationalization hint.
    req_heading = "## 7. Mandatory Requirements"
    req_position = _heading_position(visible_spec, req_heading)
    if req_position is not None:
        req_idx = req_position + len(req_heading)
        next_idx = _next_heading_idx(visible_spec, req_idx)
        req_text = visible_spec[req_idx:next_idx].lower()
        found_ambig = [
            word for word in _AMBIGUOUS_WORDS if _contains_ambiguous_word(req_text, word)
        ]
        if found_ambig:
            issues.append(
                IssuePacket(
                    issue_id="AMBIG-001",
                    section="requirements",
                    severity="minor",
                    blocking=False,
                    checklist_id="AMBIG-001",
                    problem=f"Ambiguous words in Mandatory Requirements: {found_ambig}",
                    required_change=(
                        "Preserve the locked wording and add observable acceptance criteria "
                        "and tests for this requirement."
                    ),
                )
            )

    # LOCK-COVER-001: section 7 must keep every locked ID and exact wording.
    locked_lines = _locked_requirement_lines(
        _section_content(visible_spec, "## 7. Mandatory Requirements")
    )
    for req in sheet.mandatory_requirements:
        entries = locked_lines.get(req.id, [])
        if not entries:
            issues.append(
                _locked_requirement_issue(
                    req.id,
                    "missing",
                    req.text,
                    "Add this locked line to section 7 exactly once.",
                )
            )
            continue
        if len(entries) != 1:
            issues.append(
                _locked_requirement_issue(
                    req.id,
                    "duplicate",
                    req.text,
                    "Keep this locked requirement exactly once in section 7.",
                    entries[0],
                )
            )
            continue
        if _normalize_for_coverage(entries[0]) != _normalize_for_coverage(req.text):
            issues.append(
                _locked_requirement_issue(
                    req.id,
                    "changed",
                    req.text,
                    "Restore the locked requirement wording in section 7.",
                    entries[0],
                )
            )

    # 필수 결정이 별도 분류에 있어도 잠금 원문을 동일하게 보장한다.
    parent = _heading_position(visible_spec, "## 10. Forbidden Behaviors")
    forbidden = ""
    if parent is not None:
        tail = visible_spec[parent + len("## 10. Forbidden Behaviors"):]
        following = re.search(r"(?m)^## ", tail)
        forbidden = tail[:following.start()] if following else tail
    for items, heading, content in (
        (sheet.non_scope, "### 4.2 Out of Scope", _section_content(visible_spec, "### 4.2 Out of Scope")),
        (sheet.constraints, "### Locked Constraints", _section_content(forbidden, "### Locked Constraints")),
    ):
        lines = _locked_requirement_lines(content)
        for req in items:
            entries = lines.get(req.id, [])
            condition = "missing" if not entries else "duplicate" if len(entries) != 1 else "changed" if entries[0] != req.text else None
            if condition:
                issue = _locked_requirement_issue(req.id, condition, req.text,
                    f"Restore the locked line exactly once under {heading}.", entries[0] if entries else None)
                issue.problem = f"Locked decision [{req.id}] is {condition} under {heading}."
                issue.evidence[0].source = heading
                issues.append(issue)

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


def _heading_position(text: str, heading: str) -> int | None:
    match = re.search(rf"(?m)^{re.escape(heading)}\s*$", text)
    return match.start() if match is not None else None


def _mask_fenced_code(text: str) -> str:
    """펜스 코드의 내용은 공백으로 바꾸되 줄과 인덱스는 보존한다."""
    masked: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence is None and marker:
            fence = marker.group(1)
            masked.append("".join("\n" if char == "\n" else " " for char in line))
        elif fence is not None:
            masked.append("".join("\n" if char == "\n" else " " for char in line))
            if _is_fence_close(line, fence):
                fence = None
        else:
            masked.append(line)
    return "".join(masked)


def _is_fence_close(line: str, opening: str) -> bool:
    marker = re.match(r"^ {0,3}(`+|~+)[ \t]*(?:\r?\n)?$", line)
    return bool(
        marker
        and marker.group(1)[0] == opening[0]
        and len(marker.group(1)) >= len(opening)
    )


def _normalize_for_coverage(text: str) -> str:
    return " ".join(text.casefold().split())


def _locked_requirement_lines(section: str) -> dict[str, list[str]]:
    """Return only explicit ``- [REQ-ID] wording`` lines from section 7."""
    values: dict[str, list[str]] = {}
    for line in _mask_fenced_code(section).splitlines():
        match = re.match(r"\s*[-*]\s+\[([^\]\r\n]+)\]\s+(.+?)\s*$", line)
        if match is None:
            match = re.match(
                r"\s*[-*]\s+\*\*([^:*\r\n]+):\*\*\s+(.+?)\s*$",
                line,
            )
        if match is None:
            id_only = re.match(r"\s*[-*]\s+\[([^\]\r\n]+)\]\s*$", line)
            if id_only is None:
                id_only = re.match(r"\s*[-*]\s+\*\*([^:*\r\n]+):\*\*\s*$", line)
            if id_only is not None:
                requirement_id = id_only.group(1).strip()
                if requirement_id:
                    values.setdefault(requirement_id, []).append("")
                continue
        if match is None:
            continue
        requirement_id = match.group(1).strip()
        text = match.group(2).strip()
        if requirement_id and text:
            values.setdefault(requirement_id, []).append(text)
    return values


def _locked_requirement_issue(
    requirement_id: str,
    condition: str,
    expected: str,
    required_change: str,
    actual: str | None = None,
) -> IssuePacket:
    quote = actual or expected
    return IssuePacket(
        issue_id=f"LOCK-COVER-{condition.upper()}-{requirement_id}",
        section="requirements",
        severity="blocking",
        blocking=True,
        checklist_id=f"LOCK-COVER-{condition.upper()}-{requirement_id}",
        problem=(
            f"Locked mandatory requirement [{requirement_id}] is {condition} in section 7."
        ),
        required_change=required_change,
        requirement_id=requirement_id,
        evidence=[
            IssueEvidence(
                source="## 7. Mandatory Requirements",
                quote=quote,
            )
        ],
    )


def _contains_ambiguous_word(text: str, word: str) -> bool:
    if word.isascii():
        return bool(re.search(rf"\b{re.escape(word.casefold())}\b", text))
    return word in text


def _headings_in_required_order(text: str) -> bool:
    positions = [_heading_position(text, heading) for heading in REQUIRED_FINAL_SPEC_HEADINGS]
    return all(position is not None for position in positions) and positions == sorted(positions)


def _section_content(text: str, heading: str) -> str:
    position = _heading_position(text, heading)
    if position is None:
        return ""
    start = position + len(heading)
    return text[start : _next_heading_idx(text, start)]
