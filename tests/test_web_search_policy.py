from __future__ import annotations

from pathlib import Path

import pytest


def test_web_search_on_mode_propagates_errors(
    monkeypatch: pytest.MonkeyPatch,
    mock_engine,
    tmp_path: Path,
) -> None:
    output = tmp_path / "out"

    def raise_search(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("search failed")

    monkeypatch.setattr("magi_spec.graph.nodes.web_search", raise_search)

    with pytest.raises(RuntimeError, match="search failed"):
        mock_engine.generate_from_text(
            text="Need latest SDK docs.",
            output_dir=str(output),
            web_search_mode="on",
        )


def test_web_search_auto_mode_swallows_errors(
    monkeypatch: pytest.MonkeyPatch,
    mock_engine,
    tmp_path: Path,
) -> None:
    output = tmp_path / "out"

    def raise_search(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("search failed")

    monkeypatch.setattr("magi_spec.graph.nodes.web_search", raise_search)

    result = mock_engine.generate_from_text(
        text="Need latest SDK docs.",
        output_dir=str(output),
        web_search_mode="auto",
    )

    assert result.status == "PASS_PENDING_USER_APPROVAL"
