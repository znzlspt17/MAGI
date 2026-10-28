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


def test_block_diagnostic_only_logs_allowlisted_reason_section_and_numeric_index(json_log):
    from backend.server.diagnostics import diagnose_exception
    error = SpecCompilationError(["PRIVATE_RESPONSE"], check="spec_blocks", block_reason="PRIVATE_REASON", section="PRIVATE_SECTION", index="PRIVATE_INDEX")
    error.block_reason = "PRIVATE_REASON"
    error.block_reasons = {"PRIVATE_REASON"}
    error.block_field = "PRIVATE_FIELD"
    error.block_fields = {"PRIVATE_FIELD"}
    diagnostic = diagnose_exception(error)
    assert diagnostic["validation_reason"] is None
    assert diagnostic["validation_section"] is None
    assert diagnostic["validation_index"] is None
    assert diagnostic["validation_field"] is None
    assert "PRIVATE" not in str(diagnostic)
    error = SpecCompilationError(["PRIVATE_RESPONSE"], check="spec_blocks", block_reason="unknown_requirement", section="architecture", index=2, field="requirement_ids")
    def fail(state):
        raise error
    with pytest.raises(SpecCompilationError):
        _stage("spec_compile", fail, None)({})
    rows = [json.loads(line) for line in json_log.getvalue().splitlines()]
    assert all(row["validation_reason"] == "unknown_requirement" and row["validation_section"] == "architecture" and row["validation_index"] == 2 and row["validation_field"] == "requirement_ids" for row in rows)
    assert "PRIVATE_RESPONSE" not in json_log.getvalue()


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


def test_final_job_log_preserves_stage_diagnostic(json_log, monkeypatch):
    from threading import RLock
    from types import SimpleNamespace
    from unittest.mock import Mock
    from backend.server.job_manager import JobManager
    from backend.access.validation import safe_record
    from backend.server.execution_history import _safe_result
    from gateway.logs import normalize

    error = SpecCompilationError(["PRIVATE_RESPONSE"], check="spec_blocks",
        block_reason="duplicate_item_id", section="background", index=0, field="item_id")
    engine = Mock()
    engine.execute.side_effect = lambda *a, **kw: _stage("spec_compile", lambda state: (_ for _ in ()).throw(error), None)({})
    history = Mock()
    monkeypatch.setattr("backend.server.job_manager.ExecutionHistory", Mock(return_value=history))
    job = {"execution_id": "a" * 32, "request": "PRIVATE_REQUEST"}
    manager = SimpleNamespace(lock=RLock(), _get_locked=lambda ident: job,
        _save_locked=Mock(return_value=True), _notify=Mock(), _set_error_metadata=Mock(),
        workspace=SimpleNamespace(documents=Mock(), engine=Mock(return_value=engine), state=lambda ident: {}))
    JobManager._run_logged(manager, "b" * 32, "retry", {})
    rows = [json.loads(line) for line in json_log.getvalue().splitlines()]
    assert len(rows) == 5 and rows[-1]["event"] == "job_failed"
    keys = ("validation_reason", "validation_section", "validation_index", "validation_field")
    expected = dict(zip(keys, ("duplicate_item_id", "background", 0, "item_id")))
    assert all({key: row[key] for key in keys} == expected for row in rows)
    diagnostic = history.terminal.call_args.kwargs["result"]["diagnostic"]
    assert {key: _safe_result({"diagnostic": diagnostic})["diagnostic"][key] for key in keys} == expected
    record = safe_record(json.dumps({"stage": "spec_compile", **diagnostic}))
    assert {key: record[key] for key in keys} == expected
    assert normalize(rows[-1])["fields"]["validation_field"] == "item_id"
    assert "PRIVATE" not in json_log.getvalue()
