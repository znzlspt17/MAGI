"""v2 LangGraph workflow builder — SpecForge pipeline."""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph

from magi_spec.core.state import WorkflowState
from magi_spec.schemas.issue_packet import count_unresolved_blocking, parse_issue_list


def build_v2_workflow(nodes: object):  # WorkflowNodes, avoid circular
    """Build the v2 SpecForge pipeline graph."""
    graph = StateGraph(WorkflowState)

    graph.add_node("project_context", nodes.project_context)
    graph.add_node("web_research", nodes.web_research)
    graph.add_node("interview", nodes.interview)
    graph.add_node("await_user", nodes.await_user)
    graph.add_node("requirement_lock_stage", nodes.requirement_lock_stage)
    graph.add_node("spec_compile", nodes.spec_compile)
    graph.add_node("checklist_critic", nodes.checklist_critic_node)
    graph.add_node("compose_candidate", nodes.compose_candidate)
    graph.add_node("critical_report", nodes.critical_report)

    graph.add_edge(START, "project_context")
    graph.add_edge("project_context", "web_research")
    graph.add_edge("web_research", "interview")

    graph.add_conditional_edges(
        "interview",
        route_after_interview,
        {
            "requirement_lock_stage": "requirement_lock_stage",
            "await_user": "await_user",
        },
    )

    graph.add_edge("await_user", END)
    graph.add_edge("requirement_lock_stage", "spec_compile")
    graph.add_edge("spec_compile", "checklist_critic")

    graph.add_conditional_edges(
        "checklist_critic",
        route_after_critic,
        {
            "compose_candidate": "compose_candidate",
            "spec_compile": "spec_compile",
            "critical_report": "critical_report",
        },
    )

    graph.add_edge("compose_candidate", END)
    graph.add_edge("critical_report", END)

    return graph.compile()


def route_after_interview(
    state: WorkflowState,
) -> Literal["requirement_lock_stage", "await_user"]:
    """Route after interview node."""
    if not state.get("user_request", "").strip():
        return "await_user"
    # If direction-changing blocking questions exist, pause for user input
    if state.get("blocking_questions") and state.get("_interview_direction_changing"):
        return "await_user"
    return "requirement_lock_stage"


def route_after_critic(
    state: WorkflowState,
) -> Literal["compose_candidate", "spec_compile", "critical_report"]:
    """Route after checklist critic node."""
    issues = parse_issue_list({"issues": state.get("structured_issues", [])})
    unresolved = count_unresolved_blocking(issues)
    passes = int(state.get("critic_pass_count", 0))
    max_passes = int(state.get("max_critic_passes", 2))

    if unresolved == 0:
        return "compose_candidate"
    if passes < max_passes:
        return "spec_compile"  # re-compile with issue feedback
    return "critical_report"  # exceeded max passes
