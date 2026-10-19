"""Domain errors raised by MAGI Spec Engine."""


class MagiError(Exception):
    """Base class for actionable MAGI errors."""


class MissingCredentialError(MagiError):
    """Raised when a selected provider requires unavailable credentials."""


class ArtifactError(MagiError):
    """Raised when artifact persistence fails."""


class InvalidStateError(MagiError):
    """Raised when a saved run state is malformed or not ready."""


class RequirementNormalizationError(MagiError):
    """요구사항 잠금 응답을 안전하게 정규화할 수 없을 때 발생한다."""

    code = "REQUIREMENT_NORMALIZATION_FAILED"
    stage = "requirement_lock"


class PermissionDeniedError(MagiError):
    """Raised when an agent tries to use a skill outside its permission set."""


class ConversationUnavailableError(MagiError):
    """Conversations 상태를 사용할 수 없어 새 생성이 필요할 때 발생한다."""


class ReviewValidationError(MagiError):
    """검토 응답 오류를 제품 명세 결함과 구분한다."""

    def __init__(self, details=None):
        super().__init__("Checklist review response could not be validated.")
        self.validation_details = details or ["Return a valid complete checklist review response."]


class SpecCompilationError(MagiError):
    """명세 응답의 검증 실패를 보정·공개 진단 경로로 전달한다."""

    code = "SPEC_COMPILATION_INVALID"
    stage = "spec_compile"

    def __init__(self, details):
        super().__init__("Compiler response trace could not be validated.")
        self.validation_details = details


TRANSLATION_RULES = {
    "heading_structure": "Preserve every heading level, section number and section order.",
    "heading_language": "Translate specification headings into Korean.",
    "identifiers": "Preserve every requirement ID and its occurrence count.",
    "numbers": "Preserve all numerical values and their occurrence counts.",
    "protected_content": "Preserve all code and marked original quotations verbatim.",
    "section_language": "Translate the prose of every section into Korean.",
    "document_language": "Return a Korean translation, not the English source.",
}


class TranslationValidationError(MagiError):
    """원문을 포함하지 않는 번역 보존 검증 실패."""

    code = "SPEC_TRANSLATION_INVALID"
    stage = "spec_translation"

    def __init__(self, details):
        super().__init__("Specification translation could not be validated.")
        self.validation_details = details
        self.failed_checks = [code for code, message in TRANSLATION_RULES.items() if message in details]
