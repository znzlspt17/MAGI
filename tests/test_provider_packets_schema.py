from __future__ import annotations

from magi_spec.schemas.provider_packets import (
    AnalysisPacket,
    ReviewPacket,
    choose_critical_report_markdown,
    choose_spec_markdown,
    normalize_review_status,
)


def test_review_packet_parses_and_normalizes_status() -> None:
    packet = ReviewPacket.from_provider_dict(
        {
            "status": "unknown",
            "content": "review content",
            "section_status": {"mission": "pass", "scope": "bad"},
        },
        fallback_status="PASS",
        fallback_content="fallback",
        fallback_sections={
            "mission": "PASS",
            "scope": "PASS",
        },
        allow_static_fallback=True,
        malformed_error_title="# malformed",
    )
    assert packet.status == "PASS"
    assert packet.content == "review content"
    assert packet.section_status["mission"] == "PASS"
    assert packet.section_status["scope"] == "REVISE"


def test_review_packet_non_mock_malformed_returns_revise() -> None:
    packet = ReviewPacket.from_provider_dict(
        None,
        fallback_status="PASS",
        fallback_content="fallback",
        fallback_sections={"mission": "PASS"},
        allow_static_fallback=False,
        malformed_error_title="# malformed",
    )
    assert packet.status == "REVISE"
    assert packet.section_status["mission"] == "REVISE"


def test_analysis_packet_fallback_when_missing() -> None:
    packet = AnalysisPacket.from_provider_dict(
        None,
        fallback_intent="intent",
        fallback_requirement_lock="lock",
        fallback_scope="scope",
        fallback_assumptions=["a"],
        fallback_blocking_questions=["b"],
    )
    assert packet.intent_parse == "intent"
    assert packet.assumptions == ["a"]
    assert packet.blocking_questions == ["b"]


def test_choose_spec_markdown_prefers_structured_field() -> None:
    chosen = choose_spec_markdown(
        {"spec_markdown": "# Final Agent Specification\n\n## 1. Mission"},
        raw_output="ignored",
        fallback="fallback",
    )
    assert chosen.startswith("# Final Agent Specification")


def test_choose_critical_report_markdown_uses_raw_markdown_fallback() -> None:
    chosen = choose_critical_report_markdown(
        None,
        raw_output="# CRITICAL REPORT\n\ncontent",
        fallback="fallback",
    )
    assert chosen.startswith("# CRITICAL REPORT")


def test_normalize_review_status_defaults_on_invalid() -> None:
    assert normalize_review_status("pass") == "PASS"
    assert normalize_review_status("invalid", default="REVISE") == "REVISE"
