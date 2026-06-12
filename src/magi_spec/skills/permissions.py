"""Agent skill permission matrix."""

from __future__ import annotations


INTERVIEWER = "interviewer"
CRITIC = "critic"
COMPILER = "compiler"
CRITICAL_REPORTER = "critical_reporter"


AGENT_SKILL_PERMISSIONS: dict[str, set[str]] = {
    INTERVIEWER: {
        "read_user_request",
        "scan_project_folder",
        "summarize_project_context",
        "web_search",
        "record_evidence",
        "parse_intent",
        "classify_scope",
        "generate_assumptions",
        "detect_blocking_questions",
    },
    CRITIC: {
        "read_user_request",
        "record_evidence",
        "checklist_review",
        "write_artifact",
    },
    COMPILER: {
        "compose_final_spec",
        "write_artifact",
    },
    CRITICAL_REPORTER: {
        "generate_critical_report",
        "write_artifact",
    },
}


COMMAND_CAPABLE_AGENTS = {COMPILER}
