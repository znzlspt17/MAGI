"""자격 증명이나 입력 원문을 남기지 않는 서버용 오류 진단 정보."""

from __future__ import annotations

from typing import Any
from protocol.diagnostics import traceback_frames as _traceback_frames
from backend.server.cleanup import CleanupConflict

from backend.errors import (
    ArtifactError,
    InvalidStateError,
    Error,
    MissingCredentialError,
    RequirementNormalizationError,
    ReviewValidationError,
    SpecCompilationError,
    TranslationValidationError,
)


_KNOWN_REASONS = {
    "작업 상태가 바뀌었습니다. 최신 대화를 확인하세요.": "작업 상태가 바뀌었습니다. 최신 대화를 확인하세요.",
    "문서 번역이 진행 중입니다. 번역이 끝난 뒤 다시 보내주세요.": "문서 번역이 진행 중입니다. 번역이 끝난 뒤 다시 보내주세요.",
    "이전 작업의 처리가 마무리되고 있습니다. 잠시 후 다시 시도해주세요.": "이전 작업의 처리가 마무리되고 있습니다. 잠시 후 다시 시도해주세요.",
    "공개 서비스 DB 계정은 superuser/BYPASSRLS 권한을 가질 수 없습니다.": "접속한 PostgreSQL 계정에 superuser 또는 BYPASSRLS 권한이 있습니다. DB_USER를 일반 서비스 계정으로 설정하세요. localhost 로그인도 사용자 격리를 위해 같은 조건을 적용합니다.",
    "다른 공개 백엔드 프로세스가 실행 중입니다.": "다른 공개 백엔드 프로세스가 실행 중입니다. 기존 프로세스를 확인하세요.",
    "공개 모드에는 PostgreSQL 설정이 필요합니다.": "공개 모드에는 PostgreSQL 설정이 필요합니다.",
    "Review contract is invalid. Start a new generation.": "현재 계약에 맞지 않는 검토 자료입니다. 새 작업을 생성해주세요.",
    "Requirement lock contract is invalid. Start a new generation.": "현재 계약에 맞지 않는 잠금 자료입니다. 새 작업을 생성해주세요.",
    "Validated requirement lock is required. Start a new generation.": "유효한 확정 요구사항이 없습니다. 새 작업을 생성해주세요.",
    "Checklist review response could not be validated.": "검토 응답 형식이나 추가 질문을 확인할 수 없습니다.",
    "Compiler returned an invalid English specification.": (
        "명세 생성 결과가 영어 명세 형식을 충족하지 않았습니다."
    ),
    "Interview response could not be validated.": (
        "요청 분석 결과를 확인할 수 없어 작업을 중단했습니다."
    ),
    "Interview response was not valid JSON.": (
        "요청 분석 응답이 JSON 형식이 아니어서 작업을 중단했습니다."
    ),
    "Interview response schema is invalid.": (
        "요청 분석 응답에 필요한 필드가 없거나 형식이 올바르지 않습니다."
    ),
    "Approval candidate does not exist.": "승인할 검토 후보 문서를 찾을 수 없습니다.",
    "Approval candidate must be English-only.": (
        "승인 후보 문서가 영어 전용 규칙을 충족하지 않습니다."
    ),
    "Approval candidate still has unresolved required review issues.": (
        "해결되지 않은 필수 검토 항목이 있어 승인할 수 없습니다."
    ),
    "Approval candidate no longer satisfies blocking checks.": (
        "승인 후보 문서가 필수 검토 조건을 더 이상 충족하지 않습니다."
    ),
    "Reviewed candidate is missing or invalid.": (
        "검토를 통과한 후보 문서가 없거나 형식이 올바르지 않습니다."
    ),
    "Reviewed candidate draft is missing.": "검토할 후보 초안을 찾을 수 없습니다.",
    "OpenAI returned no structured response.": "OpenAI의 구조화 응답을 확인할 수 없습니다.",
    "Output language validation failed.": "응답 언어가 단계별 규칙을 충족하지 못했습니다.",
    "OpenAI conversation creation failed.": "OpenAI 대화를 생성하지 못했습니다.",
    "Could not persist OpenAI conversation state.": "대화 연결 상태를 저장하지 못했습니다.",
    "OpenAI response did not complete.": "OpenAI 응답이 완료되지 않았습니다.",
    "OpenAI returned no text response.": "OpenAI가 텍스트 결과를 반환하지 않았습니다.",
    "OpenAI request failed.": "OpenAI 제공자 요청을 처리하지 못했습니다.",
}

# 코드와 단계는 서버가 허용한 값만 외부 작업 메타데이터에 남긴다. 예외 원문을
# 코드로 재사용하면 사용자 입력이나 제공자 응답이 작업 조회 API로 새어 나갈 수 있다.
_NORMALIZATION_ERRORS = {
    "SPEC_TRANSLATION_INVALID": {
        "stage": "spec_translation",
        "reason": "한국어 번역의 구조·수치·코드 보존을 검증하지 못했습니다. 영어 원문은 보존되어 있으며 영어 보기를 사용할 수 있습니다.",
    },
    "SPEC_COMPILATION_INVALID": {
        "stage": "spec_compile",
        "reason": "명세의 섹션·인용·출처 연결을 검증하지 못했습니다. 답변은 저장되어 있습니다. 수정 의견을 제출해 다시 시도할 수 있습니다.",
    },
    "REQUIREMENT_NORMALIZATION_FAILED": {
        "stage": "requirement_lock",
        "reason": "모델 응답을 요구사항으로 정리하지 못했습니다. 답변은 저장되어 있습니다. 수정 의견을 제출해 다시 시도할 수 있습니다.",
    },
    "SOURCE_COVERAGE_MISSING": {
        "stage": "requirement_lock",
        "reason": "모델 응답에서 일부 답변 또는 수정 의견의 연결을 확인하지 못했습니다. 답변은 저장되어 있습니다. 수정 의견을 제출해 다시 시도할 수 있습니다.",
    },
}


def diagnose_exception(exc: BaseException) -> dict[str, Any]:
    """로그에 안전한 오류 분류와 traceback 위치만 반환한다.

    예외 원문, repr, traceback의 소스 줄과 로컬 변수는 포함하지 않는다.
    """
    chain = _exception_chain(exc)
    normalization = _normalization_error(chain)
    return {
        "reason": (
            normalization["reason"]
            if normalization is not None
            else _known_reason(chain) or "작업 처리 중 오류가 발생했습니다."
        ),
        "error_code": normalization["code"] if normalization is not None else None,
        "error_stage": normalization["stage"] if normalization is not None else None,
        "failed_checks": next((
            sorted(set(check for check in item.failed_checks if isinstance(check, str) and check in item.checks))
            if isinstance(item, (ReviewValidationError, SpecCompilationError)) else item.failed_checks
            for item in chain if isinstance(item, (TranslationValidationError, ReviewValidationError, SpecCompilationError))
        ), []),
        "exception_type": type(exc).__name__,
        "cause_types": [type(item).__name__ for item in chain[1:]],
        "http_status": _http_status(chain),
        "frames": _traceback_frames(exc),
        **_block_diagnostic(chain),
    }


def _block_diagnostic(chain):
    """원문·블록 ID 대신 서버가 정한 실패 사유와 섹션·숫자 위치만 공개한다."""
    from backend.models import SpecResponse
    for item in chain:
        if not isinstance(item, SpecCompilationError) or item.failed_checks != ["spec_blocks"]:
            continue
        reason = getattr(item, "block_reason", None)
        section = getattr(item, "block_section", None)
        index = getattr(item, "block_index", None)
        field = getattr(item, "block_field", None)
        return {
            "validation_reason": reason if isinstance(reason, str) and reason in SpecCompilationError.block_reasons else None,
            "validation_section": section if isinstance(section, str) and section in SpecResponse.model_fields and section not in {"decisions", "spec_links"} else None,
            "validation_field": field if isinstance(field, str) and field in SpecCompilationError.block_fields else None,
            "validation_index": index if type(index) is int and 0 <= index <= 100000 else None,
        }
    return {"validation_reason": None, "validation_section": None, "validation_index": None, "validation_field": None}


def _normalization_error(chain: list[BaseException]) -> dict[str, str] | None:
    from backend.knowledge.setup import MigrationError

    for item in chain:
        if isinstance(item, MigrationError):
            return {"code": "DATABASE_PREPARATION_FAILED", "stage": "database", "reason": str(item)}
        if isinstance(item, ReviewValidationError):
            stage = getattr(item, "stage", None)
            return {"code": "REVIEW_VALIDATION_FAILED",
                    "stage": stage if isinstance(stage, str) and stage in ReviewValidationError.stages else "checklist_critic",
                    "reason": "검토 응답의 근거·형식 또는 추가 질문을 검증하지 못해 작업을 중단했습니다."}
        if not isinstance(item, (RequirementNormalizationError, SpecCompilationError, TranslationValidationError)):
            continue
        code = getattr(item, "code", None)
        details = _NORMALIZATION_ERRORS.get(code) if isinstance(code, str) else None
        if details is not None:
            return {"code": code, **details}
    return None


def safe_user_error(exc: BaseException) -> str:
    """화면에 노출해도 되는 고정 문구만 반환한다."""
    from backend.access.context import AccessError
    if isinstance(exc,AccessError):
        return {'quota':'오늘 사용량 한도에 도달했습니다. 입력과 결과는 보존됩니다.',
                'busy':'사용권이 종료되어 추가 처리를 중단했습니다. 기록을 확인하세요.',
                'unavailable':'서비스 설정 또는 실행 복구를 확인해야 합니다.'}.get(exc.code,'요청 권한을 확인하세요.')
    diagnostic = diagnose_exception(exc)
    reason = str(diagnostic["reason"])
    if reason != "작업 처리 중 오류가 발생했습니다.":
        return reason
    if any(
        isinstance(item, (InvalidStateError, ArtifactError, Error))
        for item in _exception_chain(exc)
    ):
        return "저장된 작업 상태 또는 입력을 확인한 뒤 다시 시도하세요."
    return reason


def _known_reason(chain: list[BaseException]) -> str | None:
    for item in chain:
        if isinstance(item, MissingCredentialError):
            return "선택한 제공자 설정을 확인하거나 데모 모드로 실행하세요."
        if not isinstance(item, (InvalidStateError, ArtifactError, Error, CleanupConflict)):
            continue
        args = item.args
        if len(args) != 1 or not isinstance(args[0], str):
            continue
        reason = _KNOWN_REASONS.get(args[0])
        if reason is not None:
            return reason
    return None


def _exception_chain(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(chain) < 8:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return chain


def _http_status(chain: list[BaseException]) -> int | None:
    """HTTP 계열 예외의 숫자 상태 코드만 제한적으로 남긴다."""
    for item in chain:
        for attribute in ("status_code", "code"):
            try:
                value = getattr(item, attribute, None)
            except Exception:
                continue
            if type(value) is int and 100 <= value <= 599:
                return value
    return None
