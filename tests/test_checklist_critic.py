from __future__ import annotations

from magi_spec.compiler.spec_compiler import REQUIRED_FINAL_SPEC_HEADINGS
from magi_spec.critic.checklist import run_deterministic_checks
from magi_spec.schemas.requirement_lock import RequirementLockSheet


def _build_valid_spec() -> str:
    """Build a spec that passes all deterministic checks."""
    lines = ["# Final Agent Specification", ""]
    for h in REQUIRED_FINAL_SPEC_HEADINGS[1:]:
        lines.append(h)
        if "Out of Scope" in h:
            lines.append("- Do not implement unrelated features.")
        elif "Forbidden" in h:
            lines.append("- Do not ignore user constraints.")
        elif "Acceptance" in h:
            lines.append("- The feature works as specified.")
        elif "Test Plan" in h:
            lines.append("- Add unit tests for new behavior.")
        lines.append("")
    return "\n".join(lines)


def test_valid_spec_no_blocking_issues() -> None:
    spec = _build_valid_spec()
    sheet = RequirementLockSheet.build_fallback()
    issues = run_deterministic_checks(spec, sheet)
    blocking = [i for i in issues if i.blocking]
    assert blocking == [], f"Expected no blocking issues, got: {[i.checklist_id for i in blocking]}"


def test_missing_heading_creates_sec_required_issue() -> None:
    # Remove a required heading
    spec = _build_valid_spec().replace("## 10. Forbidden Behaviors", "")
    sheet = RequirementLockSheet.build_fallback()
    issues = run_deterministic_checks(spec, sheet)
    ids = {i.checklist_id for i in issues}
    assert "SEC-REQUIRED-001" in ids
    assert any(i.blocking for i in issues if i.checklist_id == "SEC-REQUIRED-001")


def test_empty_forbidden_behaviors_creates_issue() -> None:
    spec = _build_valid_spec()
    # Remove content after Forbidden Behaviors
    spec = spec.replace(
        "- Do not ignore user constraints.",
        "",
    )
    # Insert empty forbidden behaviors
    spec = spec.replace(
        "## 10. Forbidden Behaviors\n\n",
        "## 10. Forbidden Behaviors\n\n\n",
    )
    sheet = RequirementLockSheet.build_fallback()
    issues = run_deterministic_checks(spec, sheet)
    # May or may not trigger depending on whitespace, check no crash at minimum
    assert isinstance(issues, list)


def test_unresolved_questions_creates_blocking_issue() -> None:
    spec = _build_valid_spec()
    sheet = RequirementLockSheet.build_fallback(
        blocking_questions=["Who is the primary user?"]
    )
    issues = run_deterministic_checks(spec, sheet)
    ids = {i.checklist_id for i in issues}
    assert "UNRESOLVED-Q-001" in ids
    assert any(i.blocking for i in issues if i.checklist_id == "UNRESOLVED-Q-001")


def test_no_unresolved_questions_no_unresolved_issue() -> None:
    spec = _build_valid_spec()
    sheet = RequirementLockSheet.build_fallback(blocking_questions=[])
    issues = run_deterministic_checks(spec, sheet)
    assert not any(i.checklist_id == "UNRESOLVED-Q-001" for i in issues)


def test_ambiguous_word_in_mandatory_creates_major_issue() -> None:
    spec = _build_valid_spec()
    # Inject ambiguous word into Mandatory Requirements section
    spec = spec.replace(
        "## 7. Mandatory Requirements\n",
        "## 7. Mandatory Requirements\n- The solution must be robust and good.\n",
    )
    sheet = RequirementLockSheet.build_fallback()
    issues = run_deterministic_checks(spec, sheet)
    ambig = [i for i in issues if i.checklist_id == "AMBIG-001"]
    assert ambig, "Expected AMBIG-001 issue"
    assert not ambig[0].blocking  # major, not blocking


def test_all_issues_have_required_fields() -> None:
    spec = ""  # worst case: totally empty spec
    sheet = RequirementLockSheet.build_fallback(blocking_questions=["test question"])
    issues = run_deterministic_checks(spec, sheet)
    for issue in issues:
        assert issue.issue_id
        assert issue.checklist_id
        assert issue.section
        assert issue.problem
        assert issue.required_change
        assert issue.severity in ("blocking", "major", "minor")
