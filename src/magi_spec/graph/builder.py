"""LangGraph workflow builder."""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph

from magi_spec.core.state import WorkflowState
from magi_spec.graph.nodes import WorkflowNodes, all_agents_pass

STAGNATION_THRESHOLD = 2


def build_workflow(nodes: WorkflowNodes):
    graph = StateGraph(WorkflowState)
    graph.add_node("project_context", nodes.project_context)
    graph.add_node("web_research", nodes.web_research)
    graph.add_node("analysis", nodes.analysis)
    graph.add_node("initial_agents", nodes.initial_agents)
    graph.add_node("review_round", nodes.review_round)
    graph.add_node("compose_candidate", nodes.compose_candidate)
    graph.add_node("critical_report", nodes.critical_report)

    graph.add_edge(START, "project_context")
    graph.add_edge("project_context", "web_research")
    graph.add_edge("web_research", "analysis")
    graph.add_conditional_edges(
        "analysis",
        route_after_analysis,
        {
            "initial_agents": "initial_agents",
            "critical_report": "critical_report",
        },
    )
    graph.add_edge("initial_agents", "review_round")
    graph.add_conditional_edges(
        "review_round",
        route_after_review,
        {
            "review_round": "review_round",
            "compose_candidate": "compose_candidate",
            "critical_report": "critical_report",
        },
    )
    graph.add_edge("compose_candidate", END)
    graph.add_edge("critical_report", END)
    return graph.compile()


def route_after_analysis(
    state: WorkflowState,
) -> Literal["initial_agents", "critical_report"]:
    if not state.get("user_request", "").strip():
        return "critical_report"
    return "initial_agents"


def route_after_review(
    state: WorkflowState,
) -> Literal["review_round", "compose_candidate", "critical_report"]:
    current_round = int(state.get("current_round", 0))
    min_rounds = int(state.get("min_rounds", 3))
    max_rounds = int(state.get("max_rounds", 10))
    if all_agents_pass(state) and current_round >= min_rounds:
        return "compose_candidate"
    if state.get("stagnant_rounds", 0) >= STAGNATION_THRESHOLD and not all_agents_pass(state):
        return "critical_report"
    if current_round >= max_rounds:
        return "critical_report"
    return "review_round"
