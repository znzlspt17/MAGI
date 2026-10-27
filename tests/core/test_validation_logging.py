"""반복 보정 실패의 검증 코드를 원문 없이 기록하는지 확인한다."""

import json
import io
from protocol.logging import configure_logging

import pytest

from backend.errors import ReviewValidationError, SpecCompilationError
from backend.infrastructure.stage_retry import CURRENT_RETRY
from backend.pipeline.builder import _stage


@pytest.fixture
def json_log():
    stream = io.StringIO()
    configure_logging("backend", stream=stream)
    yield stream
    import sys
    configure_logging("backend")


def test_review_retries_log_each_check_without_response_text(json_log):
    checks = ["source_reference", "resolution_basis", "decision_key", "question_form"]
    attempts = []

    def fail(state):
        attempt = CURRENT_RETRY.get()["attempt"]
        attempts.append(attempt)
        raise ReviewValidationError(
            ["MODEL_RESPONSE_MUST_NOT_BE_LOGGED"],
            stage="review_resolution", check=checks[attempt],
        )

    with pytest.raises(ReviewValidationError):
        _stage("review_resolution", fail, None)({})

    assert attempts == [0, 1, 2, 3]
    messages = [json.loads(line) for line in json_log.getvalue().splitlines()]
    assert len(messages) == 4
    for number, (message, check) in enumerate(zip(messages, checks), 1):
        assert message["attempt"] == number and message["max_attempts"] == 4
        assert message["failed_checks"] == [check]
        assert message["error_stage"] == "review_resolution"
    assert "MODEL_RESPONSE_MUST_NOT_BE_LOGGED" not in json_log.getvalue()
    assert CURRENT_RETRY.get() is None


def test_review_log_filters_untrusted_check_codes(json_log):
    error = ReviewValidationError(stage="review_resolution")
    error.failed_checks = ["resolution_basis", "UNTRUSTED_RESPONSE_TEXT"]

    def fail(state):
        raise error

    with pytest.raises(ReviewValidationError):
        _stage("review_resolution", fail, None)({})

    assert "resolution_basis" in json_log.getvalue()
    assert "UNTRUSTED_RESPONSE_TEXT" not in json_log.getvalue()


def test_compiler_retries_log_each_check_without_response_text(json_log):
    checks = ["source_reference", "implementation_plan", "spec_blocks", "quote_anchor"]

    def fail(state):
        raise SpecCompilationError(
            ["MODEL_RESPONSE_MUST_NOT_BE_LOGGED"],
            check=checks[CURRENT_RETRY.get()["attempt"]],
        )

    with pytest.raises(SpecCompilationError):
        _stage("spec_compile", fail, None)({})

    messages = [json.loads(line) for line in json_log.getvalue().splitlines()]
    assert len(messages) == 4
    for message, check in zip(messages, checks):
        assert message["failed_checks"] == [check]
        assert message["error_code"] == "SPEC_COMPILATION_INVALID"
        assert message["error_stage"] == "spec_compile"
    assert "MODEL_RESPONSE_MUST_NOT_BE_LOGGED" not in json_log.getvalue()
    assert CURRENT_RETRY.get() is None


def test_compiler_diagnostic_filters_untrusted_codes_and_handles_wrapped_errors():
    from backend.server.diagnostics import diagnose_exception

    error = SpecCompilationError(["PRIVATE_RESPONSE"], check="PRIVATE_CHECK")
    assert error.failed_checks == ["spec_response"]
    error.failed_checks = ["spec_blocks", "PRIVATE_CHECK", "spec_blocks"]
    wrapper = RuntimeError("PRIVATE_WRAPPER")
    wrapper.__cause__ = error
    diagnostic = diagnose_exception(wrapper)
    assert diagnostic["failed_checks"] == ["spec_blocks"]
    assert diagnostic["error_code"] == "SPEC_COMPILATION_INVALID"
    assert "PRIVATE" not in str(diagnostic)


def test_quote_anchor_failure_has_specific_check():
    from backend.services.spec_compiler import _anchor_links
    from backend.server.diagnostics import diagnose_exception

    with pytest.raises(SpecCompilationError) as raised:
        _anchor_links([{"section": "architecture", "quote": "Missing quote"}],
                      {"architecture": "Actual content"}, "assembled")
    assert diagnose_exception(raised.value)["failed_checks"] == ["quote_anchor"]
    assert raised.value.validation_phase == "assembled"


@pytest.mark.parametrize(("name", "check"), [
    ("validate_links", "spec_links"), ("validate_decisions", "decision_trace"),
])
def test_trace_failure_preserves_check_without_logging_details(name, check):
    from backend.services.spec_compiler import _validate_trace
    from backend.server.diagnostics import diagnose_exception

    def invalid():
        raise ValueError("PRIVATE_TRACE")

    invalid.__name__ = name
    with pytest.raises(SpecCompilationError) as raised:
        _validate_trace(invalid)
    diagnostic = diagnose_exception(raised.value)
    assert diagnostic["failed_checks"] == [check]
    assert "PRIVATE_TRACE" not in str(diagnostic)
