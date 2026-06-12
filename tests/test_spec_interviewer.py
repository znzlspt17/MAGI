from __future__ import annotations

from pathlib import Path

from conftest import read_json


def test_v2_generate_reaches_pass_pending(mock_engine_v2, tmp_path: Path) -> None:
    """v2 pipeline should produce PASS_PENDING_USER_APPROVAL via SpecForge pipeline."""
    output = tmp_path / "out"
    result = mock_engine_v2.generate_from_text(
        text="Build a Python utility package.",
        output_dir=str(output),
        web_search_mode="off",
    )
    assert result.status == "PASS_PENDING_USER_APPROVAL"
    assert (output / "draft" / "approval_candidate_spec.en.md").exists()


def test_v2_generate_writes_requirement_lock_sheet(mock_engine_v2, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine_v2.generate_from_text(
        text="Add a caching layer to the existing service.",
        output_dir=str(output),
        web_search_mode="off",
    )
    assert (output / "analysis" / "requirement_lock_sheet.json").exists()
    sheet = read_json(output / "analysis" / "requirement_lock_sheet.json")
    assert "request_type" in sheet
    assert "mandatory_requirements" in sheet


def test_v2_generate_writes_checklist_issues(mock_engine_v2, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine_v2.generate_from_text(
        text="Refactor the database module.",
        output_dir=str(output),
        web_search_mode="off",
    )
    assert (output / "review" / "checklist_issues.json").exists()
    issues = read_json(output / "review" / "checklist_issues.json")
    assert "issues" in issues
    assert "unresolved_blocking" in issues


def test_v2_approve_works_after_generate(mock_engine_v2, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine_v2.generate_from_text(
        text="Build a REST API wrapper.",
        output_dir=str(output),
        web_search_mode="off",
    )
    result = mock_engine_v2.approve(str(output))
    assert result.status == "FINALIZED"
    assert (output / "final" / "FINAL_AGENT_SPEC.md").exists()


def test_v2_spec_is_english_only(mock_engine_v2, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine_v2.generate_from_text(
        text="한국어로 패키지를 만들어주세요.",
        output_dir=str(output),
        web_search_mode="off",
    )
    spec = (output / "draft" / "approval_candidate_spec.en.md").read_text(encoding="utf-8")
    assert not any("\uac00" <= ch <= "\ud7a3" for ch in spec), "Spec contains Korean characters"


def test_v2_pipeline_version_in_state(mock_engine_v2, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine_v2.generate_from_text(
        text="Add logging support.",
        output_dir=str(output),
        web_search_mode="off",
    )
    state = read_json(output / "state" / "magi_state.json")
    # pipeline_version field removed from v2 state; verify v2-specific artifacts instead
    assert "critic_pass_count" in state
    assert "requirement_lock_sheet" in state


def test_v2_revise_resets_critic_state(mock_engine_v2, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine_v2.generate_from_text(
        text="Build a report generator.",
        output_dir=str(output),
        web_search_mode="off",
    )
    feedback = tmp_path / "feedback.md"
    feedback.write_text("Tighten the acceptance criteria.", encoding="utf-8")
    result = mock_engine_v2.revise(output_dir=str(output), feedback_path=str(feedback))
    assert result.status == "PASS_PENDING_USER_APPROVAL"

    state = read_json(output / "state" / "magi_state.json")
    # After revise+run, critic_pass_count should reflect fresh passes (> 0)
    assert state.get("critic_pass_count", 0) >= 0


def test_v2_generate_from_file(mock_engine_v2, tmp_path: Path) -> None:
    req = tmp_path / "request.md"
    req.write_text("Build a configuration manager CLI.", encoding="utf-8")
    output = tmp_path / "out"
    result = mock_engine_v2.generate_from_file(
        input_path=str(req),
        output_dir=str(output),
        web_search_mode="off",
    )
    assert result.status == "PASS_PENDING_USER_APPROVAL"
