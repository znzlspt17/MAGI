from __future__ import annotations

from pathlib import Path

from conftest import read_json


def test_acceptance_smoke_run(mock_engine, tmp_path: Path) -> None:
    request_file = tmp_path / "request.md"
    request_file.write_text("Build a Python package.", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("# Project", encoding="utf-8")
    output = tmp_path / "out"

    result = mock_engine.generate_from_file(
        input_path=str(request_file),
        output_dir=str(output),
        project_dir=str(project),
        web_search_mode="off",
        allow_command_execution=False,
    )

    assert result.status == "PASS_PENDING_USER_APPROVAL"
    assert (output / "raw" / "user_request.md").exists()
    assert (output / "context" / "project_manifest.json").exists()
    assert (output / "research" / "web_sources.json").exists()
    assert (output / "analysis" / "01_intent_parse.ko.md").exists()
    assert (output / "analysis" / "requirement_lock_sheet.json").exists()
    assert (output / "review" / "checklist_issues.json").exists()
    assert (output / "draft" / "approval_candidate_spec.en.md").exists()
    assert not (output / "final" / "FINAL_AGENT_SPEC.md").exists()

    state = read_json(output / "state" / "magi_state.json")
    assert state["status"] == "PASS_PENDING_USER_APPROVAL"
    assert state["command_execution_allowed"] is False

    command_log = read_json(output / "execution" / "command_log.json")
    assert command_log["commands"] == []

    approved = mock_engine.approve(str(output))
    assert approved.status == "FINALIZED"
    assert (output / "final" / "FINAL_AGENT_SPEC.md").exists()
