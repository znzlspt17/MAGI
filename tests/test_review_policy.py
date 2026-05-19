from __future__ import annotations

from magi_spec.graph.builder import route_after_analysis, route_after_review


def test_unanimous_pass_required() -> None:
    state = {
        "current_round": 3,
        "min_rounds": 3,
        "max_rounds": 10,
        "melchior_outputs": [{"status": "PASS"}],
        "balthasar_outputs": [{"status": "PASS"}],
        "casper_outputs": [{"status": "REVISE"}],
        "section_status": {"mission": "PASS"},
    }

    assert route_after_review(state) == "review_round"


def test_max_rounds_routes_to_critical() -> None:
    state = {
        "current_round": 10,
        "min_rounds": 3,
        "max_rounds": 10,
        "melchior_outputs": [{"status": "PASS"}],
        "balthasar_outputs": [{"status": "PASS"}],
        "casper_outputs": [{"status": "FAIL"}],
        "section_status": {"mission": "PASS"},
    }

    assert route_after_review(state) == "critical_report"


def test_stagnation_routes_to_critical_before_max_rounds() -> None:
    state = {
        "current_round": 4,
        "min_rounds": 3,
        "max_rounds": 10,
        "stagnant_rounds": 2,
        "melchior_outputs": [{"status": "REVISE"}],
        "balthasar_outputs": [{"status": "REVISE"}],
        "casper_outputs": [{"status": "REVISE"}],
        "section_status": {"mission": "REVISE"},
    }

    assert route_after_review(state) == "critical_report"


def test_stagnation_does_not_trigger_when_all_pass() -> None:
    """Agents that all PASS with same section_status before min_rounds must keep going."""
    state = {
        "current_round": 2,
        "min_rounds": 3,
        "max_rounds": 10,
        "stagnant_rounds": 2,
        "melchior_outputs": [{"status": "PASS"}],
        "balthasar_outputs": [{"status": "PASS"}],
        "casper_outputs": [{"status": "PASS"}],
        "section_status": {"mission": "PASS"},
    }

    assert route_after_review(state) == "review_round"


def test_blocking_questions_routes_to_critical() -> None:
    """Only a fully blank user_request triggers the early exit."""
    state = {
        "user_request": "",
        "blocking_questions": ["사용자 요청이 비어 있어 구현 방향을 결정할 수 없습니다."],
    }

    assert route_after_analysis(state) == "critical_report"


def test_no_blocking_questions_routes_to_initial_agents() -> None:
    state: dict = {
        "user_request": "Build a package.",
        "blocking_questions": [],
    }

    assert route_after_analysis(state) == "initial_agents"


def test_missing_blocking_questions_routes_to_initial_agents() -> None:
    state: dict = {
        "user_request": "Build a package.",
    }

    assert route_after_analysis(state) == "initial_agents"


def test_informational_blocking_questions_do_not_halt_workflow() -> None:
    """Informational blocking questions with a valid request must not exit early."""
    state: dict = {
        "user_request": "Build an implementation-ready specification.",
        "blocking_questions": ["외부 API 사용 여부를 확인해야 합니다."],
    }

    assert route_after_analysis(state) == "initial_agents"
