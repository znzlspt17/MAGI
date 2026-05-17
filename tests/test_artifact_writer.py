from __future__ import annotations

from pathlib import Path


REQUIRED_ARTIFACTS = [
    "raw/user_request.md",
    "context/project_manifest.json",
    "context/project_summary.ko.md",
    "research/web_sources.json",
    "research/web_research_summary.ko.md",
    "evidence/evidence_registry.json",
    "execution/command_log.json",
    "analysis/01_intent_parse.ko.md",
    "analysis/02_requirement_lock.ko.md",
    "analysis/03_scope_classification.ko.md",
    "analysis/04_initial_assumptions.ko.md",
    "analysis/05_blocking_questions.ko.md",
    "agents/initial/melchior_architecture.ko.md",
    "agents/initial/balthasar_requirements.ko.md",
    "agents/initial/casper_failure_review.ko.md",
    "draft/approval_candidate_spec.en.md",
    "state/magi_state.json",
    "state/private_model_assignments.json",
]


def test_required_artifacts_are_saved(mock_engine, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine.generate_from_text(
        text="Build artifacts.",
        output_dir=str(output),
        web_search_mode="off",
    )

    for relative in REQUIRED_ARTIFACTS:
        assert (output / relative).exists(), relative
