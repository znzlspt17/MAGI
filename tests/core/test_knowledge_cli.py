"""관리 명령은 고정 검증 안내만 노출하고 실패 단계를 표시한다."""

import sys

import pytest

from backend.knowledge import __main__ as cli
from backend.knowledge import upgrade
from backend.knowledge.config import KnowledgeConfig, KnowledgeError


@pytest.mark.parametrize("phase", ["migrate_business", "initialize_checkpoints", "convert_checkpoints"])
@pytest.mark.parametrize("safe", [True, False])
def test_migrate_reports_phase_without_unexpected_error_text(monkeypatch, capsys, phase, safe):
    monkeypatch.setattr(cli.KnowledgeConfig, "from_env", lambda: KnowledgeConfig({}))
    monkeypatch.setattr(cli, "KnowledgeStore", lambda config: object())
    monkeypatch.setattr(sys, "argv", ["knowledge", "migrate"])
    monkeypatch.setattr(upgrade, "migrate_business", lambda store: {})
    monkeypatch.setattr(upgrade, "initialize_checkpoints", lambda store: None)
    monkeypatch.setattr(upgrade, "convert_checkpoints", lambda store: 0)

    def fail(store):
        if safe:
            raise KnowledgeError("원본 문서 해시가 일치하지 않습니다.")
        raise ValueError("unexpected-private-input")

    monkeypatch.setattr(upgrade, phase, fail)
    with pytest.raises(SystemExit) as caught:
        cli.main()
    assert caught.value.code == 1
    output = capsys.readouterr().err
    assert phase in output
    assert "unexpected-private-input" not in output
    assert ("원본 문서 해시가 일치하지 않습니다." in output) == safe
