from __future__ import annotations

import pytest

from magi_spec.schemas.issue_packet import (
    IssuePacket,
    count_unresolved_blocking,
    merge_issue_lists,
    parse_issue_list,
)


def test_blocking_severity_sets_blocking_true() -> None:
    data = {
        "issue_id": "AC-001",
        "section": "acceptance",
        "severity": "blocking",
        "blocking": False,  # ignored; derived from severity
        "checklist_id": "AC-001",
        "problem": "AC not verifiable",
        "required_change": "Rewrite",
    }
    issue = IssuePacket.from_dict(data)
    assert issue.severity == "blocking"
    assert issue.blocking is True


def test_major_severity_blocking_false() -> None:
    data = {
        "issue_id": "AMBIG-001",
        "section": "requirements",
        "severity": "major",
        "checklist_id": "AMBIG-001",
        "problem": "Ambiguous wording",
        "required_change": "Fix wording",
    }
    issue = IssuePacket.from_dict(data)
    assert issue.severity == "major"
    assert issue.blocking is False


def test_unknown_severity_defaults_to_major() -> None:
    data = {"issue_id": "X", "section": "x", "severity": "unknown",
            "checklist_id": "X", "problem": "", "required_change": ""}
    issue = IssuePacket.from_dict(data)
    assert issue.severity == "major"
    assert issue.blocking is False


def test_parse_issue_list_from_dict_with_issues_key() -> None:
    data = {
        "issues": [
            {"issue_id": "A", "section": "s", "severity": "blocking",
             "checklist_id": "A", "problem": "p", "required_change": "r"},
            {"issue_id": "B", "section": "s", "severity": "minor",
             "checklist_id": "B", "problem": "p", "required_change": "r"},
        ]
    }
    issues = parse_issue_list(data)
    assert len(issues) == 2
    assert issues[0].blocking is True
    assert issues[1].blocking is False


def test_parse_issue_list_from_raw_list() -> None:
    raw = [{"issue_id": "A", "section": "s", "severity": "blocking",
            "checklist_id": "A", "problem": "p", "required_change": "r"}]
    issues = parse_issue_list(raw)
    assert len(issues) == 1


def test_parse_issue_list_none_returns_empty() -> None:
    assert parse_issue_list(None) == []


def test_parse_issue_list_malformed_string_returns_empty() -> None:
    assert parse_issue_list("garbage") == []


def test_parse_issue_list_skips_invalid_entries() -> None:
    data = {"issues": [None, "bad", {"issue_id": "A", "severity": "blocking",
                                      "section": "s", "checklist_id": "A",
                                      "problem": "p", "required_change": "r"}]}
    issues = parse_issue_list(data)
    assert len(issues) == 1


def test_count_unresolved_blocking_excludes_resolved() -> None:
    issues = [
        IssuePacket("A", "s", "blocking", True, "A", "p", "r", status="open"),
        IssuePacket("B", "s", "blocking", True, "B", "p", "r", status="resolved"),
        IssuePacket("C", "s", "major", False, "C", "p", "r", status="open"),
    ]
    assert count_unresolved_blocking(issues) == 1


def test_count_unresolved_blocking_all_resolved() -> None:
    issues = [
        IssuePacket("A", "s", "blocking", True, "A", "p", "r", status="resolved"),
    ]
    assert count_unresolved_blocking(issues) == 0


def test_merge_issue_lists_deduplicates_by_checklist_id() -> None:
    base = [IssuePacket("A", "s", "blocking", True, "CID-A", "p", "r")]
    extra = [
        IssuePacket("B", "s", "major", False, "CID-A", "p2", "r2"),  # dup checklist_id
        IssuePacket("C", "s", "major", False, "CID-B", "p3", "r3"),  # new
    ]
    merged = merge_issue_lists(base, extra)
    assert len(merged) == 2
    checklist_ids = {i.checklist_id for i in merged}
    assert "CID-A" in checklist_ids
    assert "CID-B" in checklist_ids


def test_issue_to_dict_roundtrip() -> None:
    original = IssuePacket("A", "acceptance", "blocking", True, "AC-001",
                           "prob", "fix", status="open")
    d = original.to_dict()
    restored = IssuePacket.from_dict(d)
    assert restored.issue_id == original.issue_id
    assert restored.severity == original.severity
    assert restored.blocking == original.blocking
    assert restored.status == original.status
