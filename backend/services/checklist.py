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
        "범위 제외 (### 4.2 범위 제외) 섹션이 비어있지 않음",
    ),
    ChecklistItem(
        "FORBIDDEN-001",
        "forbidden",
        "blocking",
        "## 10. 금지 행동 섹션이 비어있지 않음",
    ),
    ChecklistItem(
        "AC-001",
        "acceptance",
        "blocking",
        "## 20. 수용 기준 섹션이 비어있지 않음",
    ),
    ChecklistItem(
        "AC-QUALITY-001",
        "acceptance",
        "major",
        "수용 기준에 최종 명세 완료 같은 자리표시자가 없음",
    ),
    ChecklistItem(
        "TEST-001",
        "test_plan",
        "blocking",
        "## 21. 테스트 계획 섹션이 비어있지 않음",
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
    r"^\s*(?:[-*]\s*)?(?:\d+[.)]\s*)?(?:final spec includes|최종 명세(?:에|는)?\s*(?:포함(?:한다|합니다|되어 있다)?)?)(?:\s*(?:\.\.\.|…|\.))?\s*$",
    re.IGNORECASE,
)
_GENERIC_COMPLETION_ACCEPTANCE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\d+[.)]\s*)?(?:final spec includes "
    r"(?=[^.]*\bscope\b)(?=[^.]*\bforbidden behaviors\b)"
    r"(?=[^.]*\bacceptance criteria\b)(?=[^.]*\btest plan\b)[^.]+|"
    r"최종\s*명세(?:에|는)?\s*(?=[^.]*범위)(?=[^.]*금지\s*행동)"
    r"(?=[^.]*수용\s*기준)(?=[^.]*테스트\s*계획)[^.]*포함[^.]*)\.?\s*$",
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
                problem=f"필수 제목이 누락되었습니다: {missing_headings[:5]}",
                required_change="필수 제목을 모두 순서대로 추가하세요.",
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
                problem="필수 제목의 순서가 올바르지 않습니다.",
                required_change="필수 제목을 지정된 순서로 복원하세요.",
            )
        )

    # SCOPE-NONSCOPE-001: Out of Scope not empty
    oos_heading = "### 4.2 범위 제외"
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
                    problem="범위 제외 섹션이 비어 있습니다.",
                    required_change="명시적인 범위 제외 항목을 하나 이상 작성하세요.",
                )
            )

    # FORBIDDEN-001: Forbidden Behaviors not empty
    fb_heading = "## 10. 금지 행동"
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
                    problem="금지 행동 섹션이 비어 있습니다.",
                    required_change="명시적인 금지 행동을 하나 이상 작성하세요.",
                )
            )

    # AC-001: Acceptance Criteria not empty
    ac_heading = "## 20. 수용 기준"
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
                    problem="수용 기준 섹션이 비어 있습니다.",
                    required_change="검증 가능한 수용 기준을 하나 이상 작성하세요.",
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
                    "자리표시자를 관찰 가능한 행동, 기대 결과, "
                    "검증 방법으로 교체하세요."
                    if only_placeholders
                    else "중복된 완료 요약 자리표시자를 제거하세요."
                )
                issues.append(
                    IssuePacket(
                        issue_id="AC-QUALITY-001",
                        section="acceptance",
                        severity=severity,
                        blocking=False,
                        checklist_id="AC-QUALITY-001",
                        problem=(
                            "수용 기준에 최종 명세의 일반적인 완료 "
                            "자리표시자가 있습니다."
                        ),
                        required_change=required_change,
                    )
                )

    # TEST-001: Test Plan not empty
    tp_heading = "## 21. 테스트 계획"
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
                    problem="테스트 계획 섹션이 비어 있습니다.",
                    required_change="테스트 전략을 하나 이상 작성하세요.",
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
                problem=f"해결되지 않은 필수 질문: {sheet.unresolved_questions[:3]}",
                required_change="명세를 확정하기 전에 모든 필수 질문을 해결하세요.",
            )
        )

    # AMBIG-001: locked wording is preserved; flag it only as an operationalization hint.
    req_heading = "## 7. 필수 요구사항"
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
                    problem=f"필수 요구사항에 모호한 표현이 있습니다: {found_ambig}",
                    required_change=(
                        "확정된 표현을 보존하고 관찰 가능한 수용 기준과 "
                        "테스트를 추가하세요."
                    ),
                )
            )

    # LOCK-COVER-001: section 7 must keep every locked ID and exact wording.
    locked_lines = _locked_requirement_lines(
        _section_content(visible_spec, "## 7. 필수 요구사항")
    )
    for req in sheet.mandatory_requirements:
        entries = locked_lines.get(req.id, [])
        if not entries:
            issues.append(
                _locked_requirement_issue(
                    req.id,
                    "missing",
                    req.text,
                    "확정된 항목을 7번 섹션에 정확히 한 번 추가하세요.",
                )
            )
            continue
        if len(entries) != 1:
            issues.append(
                _locked_requirement_issue(
                    req.id,
                    "duplicate",
                    req.text,
                    "확정된 요구사항을 7번 섹션에 정확히 한 번 유지하세요.",
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
                    "7번 섹션의 확정된 요구사항 문구를 복원하세요.",
                    entries[0],
                )
            )

    # 필수 결정이 별도 분류에 있어도 잠금 원문을 동일하게 보장한다.
    parent = _heading_position(visible_spec, "## 10. 금지 행동")
    forbidden = ""
    if parent is not None:
        tail = visible_spec[parent + len("## 10. 금지 행동"):]
        following = re.search(r"(?m)^## ", tail)
        forbidden = tail[:following.start()] if following else tail
    for items, heading, content in (
        (sheet.non_scope, "### 4.2 범위 제외", _section_content(visible_spec, "### 4.2 범위 제외")),
        (sheet.constraints, "### 확정된 제약", _section_content(forbidden, "### 확정된 제약")),
    ):
        lines = _locked_requirement_lines(content)
        for req in items:
            entries = lines.get(req.id, [])
            condition = "missing" if not entries else "duplicate" if len(entries) != 1 else "changed" if entries[0] != req.text else None
            if condition:
                issue = _locked_requirement_issue(req.id, condition, req.text,
                    f"확정된 항목을 {heading} 아래에 정확히 한 번 복원하세요.", entries[0] if entries else None)
                issue.problem = f"확정된 결정 [{req.id}]이 {heading}에서 {condition} 상태입니다."
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
            f"확정된 필수 요구사항 [{requirement_id}]이 7번 섹션에서 {condition} 상태입니다."
        ),
        required_change=required_change,
        requirement_id=requirement_id,
        evidence=[
            IssueEvidence(
                source="## 7. 필수 요구사항",
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
    return all(position is not None for position in positions) and positions == sorted(position for position in positions if position is not None)


def _section_content(text: str, heading: str) -> str:
    position = _heading_position(text, heading)
    if position is None:
        return ""
    start = position + len(heading)
    return text[start : _next_heading_idx(text, start)]
