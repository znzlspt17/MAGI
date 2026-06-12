"""Question templates for the v2 Spec Interviewer."""

from __future__ import annotations

from dataclasses import dataclass, field


HARD_CAP = 7


@dataclass(slots=True)
class Question:
    question_id: str
    text: str
    direction_changing: bool  # True → workflow may pause for user input if unanswered
    applies_to: tuple[str, ...]  # request types, or ("*",) for all


# Common questions applied regardless of request type
COMMON_QUESTIONS: list[Question] = [
    Question(
        "FORBIDDEN-001",
        "절대 수정하거나 삭제하면 안 되는 파일·기능·API가 있습니까?",
        True,
        ("*",),
    ),
    Question(
        "DONE-001",
        "무엇이 충족되면 이 작업이 완료된 것으로 봅니까? (완료 기준 / Acceptance Criteria 씨앗)",
        True,
        ("*",),
    ),
]

QUESTION_SETS: dict[str, list[Question]] = {
    "product": [
        Question(
            "PRODUCT-001",
            "최종 산출물 형태가 무엇입니까? (라이브러리, CLI, 웹 서비스, 데스크톱 앱 등)",
            True,
            ("product",),
        ),
        Question(
            "PRODUCT-002",
            "최종 사용자는 개발자입니까, 비개발자입니까?",
            True,
            ("product",),
        ),
        Question(
            "PRODUCT-003",
            "배포 방식이나 설치 방법에 특별한 요구사항이 있습니까?",
            False,
            ("product",),
        ),
    ],
    "feature": [
        Question(
            "FEATURE-001",
            "이 기능이 받아야 할 입력과 생성해야 할 출력(파일·반환값·부작용)은 무엇입니까?",
            True,
            ("feature",),
        ),
        Question(
            "FEATURE-002",
            "이 기능이 영향을 주어서는 안 되는 기존 모듈·동작이 있습니까?",
            True,
            ("feature",),
        ),
        Question(
            "FEATURE-003",
            "외부 API·라이브러리·서드파티 서비스를 사용합니까? 버전 제약이 있습니까?",
            False,
            ("feature",),
        ),
    ],
    "bugfix": [
        Question(
            "BUG-001",
            "버그를 재현하는 최소 조건은 무엇입니까?",
            True,
            ("bugfix",),
        ),
        Question(
            "BUG-002",
            "이 수정이 다른 기능에 회귀를 일으킬 위험이 있습니까?",
            True,
            ("bugfix",),
        ),
        Question(
            "BUG-003",
            "수정 후 저장된 데이터(DB·파일)에 영향을 주는 변경이 있습니까?",
            True,
            ("bugfix",),
        ),
    ],
    "refactor": [
        Question(
            "REFACTOR-001",
            "리팩토링 후에도 보존되어야 하는 외부 동작(API, CLI 인터페이스, 파일 형식)을 명시해 주세요.",
            True,
            ("refactor",),
        ),
        Question(
            "REFACTOR-002",
            "리팩토링 중 변경해서는 안 되는 모듈·파일이 있습니까?",
            True,
            ("refactor",),
        ),
    ],
    "infra": [
        Question(
            "INFRA-001",
            "변경이 프로덕션 환경에 즉시 영향을 줍니까, 아니면 단계적으로 배포합니까?",
            True,
            ("infra",),
        ),
        Question(
            "INFRA-002",
            "롤백 계획이나 다운타임 허용 여부를 알려주세요.",
            True,
            ("infra",),
        ),
    ],
}


def classify_request_type(user_request: str, manifest: dict) -> str:
    """Heuristically determine request type from text and project manifest."""
    text = user_request.lower()
    file_count = manifest.get("file_count", 0) if isinstance(manifest, dict) else 0

    # Explicit keyword signals
    if any(w in text for w in ("fix", "bug", "error", "crash", "오류", "버그", "수정")):
        return "bugfix"
    if any(w in text for w in ("refactor", "리팩토링", "restructure", "cleanup", "clean up")):
        return "refactor"
    if any(w in text for w in ("infra", "infrastructure", "deploy", "ci", "cd", "인프라", "배포")):
        return "infra"
    if file_count == 0 and any(
        w in text for w in ("build", "create", "make", "만들", "새로", "from scratch", "new project")
    ):
        return "product"
    # Default
    return "feature"


def select_questions(
    request_type: str,
    *,
    answered_ids: set[str] | None = None,
) -> list[Question]:
    """Return ordered questions for the request type, respecting HARD_CAP.

    Direction-changing questions are prioritised over informational ones.
    Already-answered questions (by question_id) are excluded.
    """
    answered = answered_ids or set()
    type_qs = QUESTION_SETS.get(request_type, QUESTION_SETS["feature"])
    all_qs = type_qs + COMMON_QUESTIONS

    # Filter answered
    remaining = [q for q in all_qs if q.question_id not in answered]

    # Sort: direction_changing first
    remaining.sort(key=lambda q: (0 if q.direction_changing else 1, q.question_id))

    return remaining[:HARD_CAP]
