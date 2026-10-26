"""반복 보정 실패의 검증 코드를 원문 없이 기록하는지 확인한다."""

import logging

import pytest

from backend.errors import ReviewValidationError
from backend.infrastructure.stage_retry import CURRENT_RETRY
from backend.pipeline.builder import _stage


def test_review_retries_log_each_check_without_response_text(caplog):
    checks = ["source_reference", "resolution_basis", "decision_key", "question_form"]
    attempts = []

    def fail(state):
        attempt = CURRENT_RETRY.get()["attempt"]
        attempts.append(attempt)
        raise ReviewValidationError(
            ["MODEL_RESPONSE_MUST_NOT_BE_LOGGED"],
            stage="review_resolution", check=checks[attempt],
        )

    with caplog.at_level(logging.WARNING, logger="backend.server"):
        with pytest.raises(ReviewValidationError):
            _stage("review_resolution", fail, None)({})

    assert attempts == [0, 1, 2, 3]
    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 4
    for number, (message, check) in enumerate(zip(messages, checks), 1):
        assert f"attempt={number} max_attempts=4" in message
        assert f"failed_checks=['{check}']" in message
        assert "error_stage=review_resolution" in message
    assert "MODEL_RESPONSE_MUST_NOT_BE_LOGGED" not in caplog.text
    assert CURRENT_RETRY.get() is None


def test_review_log_filters_untrusted_check_codes(caplog):
    error = ReviewValidationError(stage="review_resolution")
    error.failed_checks = ["resolution_basis", "UNTRUSTED_RESPONSE_TEXT"]

    def fail(state):
        raise error

    with caplog.at_level(logging.WARNING, logger="backend.server"):
        with pytest.raises(ReviewValidationError):
            _stage("review_resolution", fail, None)({})

    assert "resolution_basis" in caplog.text
    assert "UNTRUSTED_RESPONSE_TEXT" not in caplog.text
