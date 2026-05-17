"""Agent skill permission matrix."""

from __future__ import annotations


MELCHIOR = "melchior"
BALTHASAR = "balthasar"
CASPER = "casper"
CONFLICT_RESOLVER = "conflict_resolver"
SPEC_COMPOSER = "spec_composer"
CRITICAL_REPORTER = "critical_reporter"


AGENT_SKILL_PERMISSIONS: dict[str, set[str]] = {
    MELCHIOR: {
        "read_user_request",
        "scan_project_folder",
        "read_project_file",
        "summarize_project_context",
        "web_search",
        "record_evidence",
        "architecture_review",
        "cross_review",
        "execute_command_guarded",
    },
    BALTHASAR: {
        "read_user_request",
        "scan_project_folder",
        "read_project_file",
        "summarize_project_context",
        "web_search",
        "record_evidence",
        "parse_intent",
        "classify_scope",
        "generate_assumptions",
        "detect_blocking_questions",
        "requirement_review",
        "cross_review",
    },
    CASPER: {
        "read_user_request",
        "scan_project_folder",
        "read_project_file",
        "summarize_project_context",
        "web_search",
        "record_evidence",
        "failure_review",
        "cross_review",
        "execute_command_guarded",
    },
    CONFLICT_RESOLVER: {
        "record_evidence",
        "resolve_conflicts",
        "write_artifact",
    },
    SPEC_COMPOSER: {
        "compose_final_spec",
        "write_artifact",
    },
    CRITICAL_REPORTER: {
        "generate_critical_report",
        "write_artifact",
    },
}


COMMAND_CAPABLE_AGENTS = {MELCHIOR, CASPER}
