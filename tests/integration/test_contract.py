"""명령 입력과 RPC 등록이 같은 공개 계약을 사용하는지 검사한다."""

import json
import pytest
from pydantic import ValidationError
from protocol.commands import JobCommand
from protocol.messages import RPC_METHODS, parse_request
from backend.server.app import Server


def test_command_registry_and_removed_endpoints():
    assert all(
        handler is None or callable(getattr(Server, handler))
        for handler in RPC_METHODS.values()
    )
    packet = {
        "request_id": "test",
        "method": "job.command",
        "params": {"kind": "generate", "input": "메모"},
    }
    assert parse_request(json.dumps(packet)) is not None
    for method in ["generate", "answer", "approve", "retry", "projects.assign", "admin.claim"]:
        assert parse_request(json.dumps({**packet, "method": method})) is None
    for params in [
        {"kind": "approve", "job_id": "a", "execution_id": "e"},
        {"kind": "answer", "input": []},
        {"kind": "generate", "input": "메모", "execution_id": "e"},
        {"kind": "generate", "input": "메모", "replay_pending": False},
        {"kind": "retry", "job_id": "a", "execution_id": "e", "replay_pending": "true"},
    ]:
        with pytest.raises(ValidationError):
            JobCommand.model_validate(params)
    assert JobCommand(kind="retry",job_id="a",execution_id="e",replay_pending=True).parameters()["replay_pending"] is True
