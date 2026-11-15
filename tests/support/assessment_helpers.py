"""여러 테스트에서 공유하는 검증용 도우미."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from backend.pipeline.agent_workflow import AgentWorkflow


def workflow():
    nodes = SimpleNamespace(
        interview=AsyncMock(return_value={"blocking_questions": []}),
        review_resolution=AsyncMock(return_value={"blocking_questions": []}),
        await_user=lambda state: {"status": "NEEDS_USER_INPUT", "blocking_questions": state["blocking_questions"]},
        critical_report=AsyncMock(return_value={"critical_report": "report"}),
    )
    flow = AgentWorkflow(SimpleNamespace(config=SimpleNamespace(max_critic_passes=3)), nodes, None, None)
    flow.persist = AsyncMock()
    flow._candidate_hash = AsyncMock(return_value="draft")
    async def durable(name, state, operation, *, projection_stage=None):
        return await operation(state)
    flow.durable = durable
    return flow
