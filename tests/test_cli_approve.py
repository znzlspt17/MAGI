from __future__ import annotations

from pathlib import Path

import pytest

from magi_spec.core.errors import InvalidStateError


def test_approve_promotes_candidate(mock_engine, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine.generate_from_text(
        text="Build a reviewed package.",
        output_dir=str(output),
        web_search_mode="off",
    )

    assert not (output / "final" / "FINAL_AGENT_SPEC.md").exists()
    result = mock_engine.approve(str(output))

    assert result.status == "FINALIZED"
    assert (output / "final" / "FINAL_AGENT_SPEC.md").exists()


def test_approve_rejects_invalid_state(mock_engine, tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    (output / "state").mkdir()
    (output / "state" / "magi_state.json").write_text(
        '{"run_id":"x","status":"DRAFT","user_request":"","input_source":"","project_dir":null,"output_dir":"'
        + str(output).replace("\\", "\\\\")
        + '"}',
        encoding="utf-8",
    )

    with pytest.raises(InvalidStateError):
        mock_engine.approve(str(output))
