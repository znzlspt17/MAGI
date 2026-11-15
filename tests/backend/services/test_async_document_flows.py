from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.backend.application.async_helpers import run_async
from backend.services.requirement_review import load_snapshot
from backend.services.impact_review import run_review
from backend.services.interviewer import SpecInterviewer
from backend.models import InterviewResponse
from backend.mcp_client.workflow import interview_messages


@run_async
async def test_requirement_snapshot_waits_for_document_lookup():
    writer = SimpleNamespace(exists=AsyncMock(return_value=False))
    assert await load_snapshot(writer, 'a' * 64, 'spec') is None
    writer.exists.assert_awaited_once()


@run_async
async def test_impact_review_recovers_interrupted_persisted_report():
    writer = SimpleNamespace(exists=AsyncMock(return_value=True),
                             read_json=AsyncMock(return_value={'status': 'running'}))
    report = await run_review(writer, None, None, ('id', [], {}, {}), {})
    assert report['status'] == 'interrupted'
    writer.read_json.assert_awaited_once()


@run_async
async def test_interviewer_waits_for_async_provider():
    provider = AsyncMock(return_value=InterviewResponse(request_type='feature', assumptions=[],
                         blocking_questions=[], additional_questions=[], pre_answers=[]))
    result = await SpecInterviewer().run({'user_request': '메모 저장'}, {}, provider_messages_fn=provider)
    assert result.request_type == 'feature'
    provider.assert_awaited_once()


@run_async
async def test_mcp_interview_reads_manifest_asynchronously():
    writer = SimpleNamespace(read_json=AsyncMock(return_value={'platform': 'desktop'}))
    nodes = SimpleNamespace(interviewer=SimpleNamespace(prepare_messages=lambda state, manifest: [manifest]))
    assert await interview_messages(nodes, writer, {}) == [{'platform': 'desktop'}]
    writer.read_json.assert_awaited_once()
