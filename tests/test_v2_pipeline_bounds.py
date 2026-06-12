from __future__ import annotations

from magi_spec.pipeline.builder import route_after_critic, route_after_interview
from magi_spec.schemas.issue_packet import IssuePacket


def _state_with_issues(issues: list[IssuePacket], passes: int, max_passes: int = 2) -> dict:
    return {
        "user_request": "Build something.",
        "structured_issues": [i.to_dict() for i in issues],
        "critic_pass_count": passes,
        "max_critic_passes": max_passes,
        "blocking_questions": [],
    }


def test_no_blocking_issues_routes_to_compose() -> None:
    issues = [IssuePacket("A", "s", "major", False, "AMBIG-001", "p", "r", status="open")]
    state = _state_with_issues(issues, passes=1)
    assert route_after_critic(state) == "compose_candidate"


def test_unresolved_blocking_within_passes_routes_to_spec_compile() -> None:
    issues = [IssuePacket("A", "s", "blocking", True, "SEC-001", "p", "r", status="open")]
    state = _state_with_issues(issues, passes=1, max_passes=2)
    assert route_after_critic(state) == "spec_compile"


def test_unresolved_blocking_exceeded_passes_routes_to_critical() -> None:
    issues = [IssuePacket("A", "s", "blocking", True, "SEC-001", "p", "r", status="open")]
    state = _state_with_issues(issues, passes=2, max_passes=2)
    assert route_after_critic(state) == "critical_report"


def test_critic_max_passes_is_2_by_default() -> None:
    """After exactly 2 passes with blocking issues, must go to critical."""
    issues = [IssuePacket("A", "s", "blocking", True, "SEC-001", "p", "r")]
    state = {
        "user_request": "Build.",
        "structured_issues": [i.to_dict() for i in issues],
        "critic_pass_count": 2,
        "blocking_questions": [],
        # no max_critic_passes key → defaults to 2
    }
    assert route_after_critic(state) == "critical_report"


def test_critic_loop_bounded_to_max_passes() -> None:
    """Regardless of issues, critic never routes back to spec_compile more than max_passes times."""
    issues = [IssuePacket("A", "s", "blocking", True, "SEC-001", "p", "r")]
    for passes in range(3):
        state = _state_with_issues(issues, passes=passes, max_passes=2)
        route = route_after_critic(state)
        if passes < 2:
            assert route == "spec_compile", f"Expected spec_compile at pass {passes}"
        else:
            assert route == "critical_report", f"Expected critical_report at pass {passes}"


def test_resolved_blocking_routes_to_compose() -> None:
    """Resolved blocking issues do not count toward unresolved."""
    issues = [
        IssuePacket("A", "s", "blocking", True, "SEC-001", "p", "r", status="resolved"),
        IssuePacket("B", "s", "major", False, "AMBIG-001", "p", "r", status="open"),
    ]
    state = _state_with_issues(issues, passes=1)
    assert route_after_critic(state) == "compose_candidate"


def test_route_after_interview_empty_request_goes_to_await_user() -> None:
    state = {"user_request": "", "blocking_questions": []}
    assert route_after_interview(state) == "await_user"


def test_route_after_interview_normal_request_goes_to_lock() -> None:
    state = {
        "user_request": "Build a package.",
        "blocking_questions": [],
        "_interview_direction_changing": False,
    }
    assert route_after_interview(state) == "requirement_lock_stage"


def test_route_after_interview_direction_changing_goes_to_await_user() -> None:
    state = {
        "user_request": "Build a package.",
        "blocking_questions": ["What is the target platform?"],
        "_interview_direction_changing": True,
    }
    assert route_after_interview(state) == "await_user"


def test_route_after_interview_blocking_without_direction_changing_continues() -> None:
    """Non-direction-changing blocking questions don't halt the pipeline."""
    state = {
        "user_request": "Build a package.",
        "blocking_questions": ["Some informational question"],
        "_interview_direction_changing": False,
    }
    assert route_after_interview(state) == "requirement_lock_stage"
