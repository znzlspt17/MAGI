"""여러 테스트에서 공유하는 검증용 도우미."""

from types import SimpleNamespace
from unittest.mock import Mock
from backend.pipeline.agent_workflow import AgentWorkflow


def workflow():
    nodes = SimpleNamespace(
        interview=Mock(return_value={"blocking_questions": []}),
        review_resolution=Mock(return_value={"blocking_questions": []}),
        await_user=lambda state: {"status": "NEEDS_USER_INPUT", "blocking_questions": state["blocking_questions"]},
        critical_report=Mock(return_value={"critical_report": "report"}),
    )
    flow = AgentWorkflow(SimpleNamespace(config=SimpleNamespace(max_critic_passes=3)), nodes, None, None)
    flow.persist = Mock()
    flow._candidate_hash = lambda: "draft"
    flow.durable = lambda name, state, operation: operation(state)
    return flow
