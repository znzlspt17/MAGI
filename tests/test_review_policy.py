from __future__ import annotations

from magi_spec.graph.builder import route_after_review


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
