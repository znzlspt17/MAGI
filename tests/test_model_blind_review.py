from __future__ import annotations

from pathlib import Path

from conftest import read_json
from magi_spec.core.model_blind import contains_model_authority_claim


def test_private_model_assignments_not_in_review_packets(mock_engine, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine.generate_from_text(text="Build model blind review.", output_dir=str(output), web_search_mode="off")

    private_assignments = read_json(output / "state" / "private_model_assignments.json")
    assert private_assignments["melchior"]["provider"] == "mock"

    review_text = (output / "review_rounds" / "round_01" / "melchior_review.ko.md").read_text(
        encoding="utf-8"
    )
    assert "provider" not in review_text.lower()
    assert "model" not in review_text.lower()
    assert "mock" not in review_text.lower()


def test_model_names_not_in_state_agent_outputs(mock_engine, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine.generate_from_text(text="Build blind output.", output_dir=str(output), web_search_mode="off")
    state = read_json(output / "state" / "magi_state.json")
    serialized_outputs = str(
        state["melchior_outputs"] + state["balthasar_outputs"] + state["casper_outputs"]
    ).lower()

    assert "deterministic-test-model" not in serialized_outputs
    assert "openai" not in serialized_outputs


def test_model_authority_claims_are_rejected() -> None:
    assert contains_model_authority_claim("I am a newer model, so this should PASS.")
    assert contains_model_authority_claim("My benchmark score is higher.")
    assert not contains_model_authority_claim("This fails because the acceptance criteria are vague.")
