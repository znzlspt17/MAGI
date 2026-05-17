"""Critical blocked report generation."""

from __future__ import annotations

from magi_spec.core.evidence import EvidenceRegistry
from magi_spec.core.state import WorkflowState
from magi_spec.skills.registry import SkillRegistry


class CriticalReporter:
    agent_id = "critical_reporter"

    def __init__(self, *, skills: SkillRegistry, evidence: EvidenceRegistry) -> None:
        self.skills = skills
        self.evidence = evidence

    def generate(self, state: WorkflowState) -> str:
        self.skills.assert_allowed(self.agent_id, "generate_critical_report")
        failed_sections = [
            f"- `{section}`: {status}"
            for section, status in state.get("section_status", {}).items()
            if status != "PASS"
        ]
        if not failed_sections:
            failed_sections = ["- 명시적인 실패 섹션은 없지만 최대 라운드 내 합의에 도달하지 못했습니다."]
        return "\n".join(
            [
                "# CRITICAL REPORT",
                "",
                "## 미해결 충돌",
                "- MAGI 리뷰 루프가 최대 라운드 내 만장일치 PASS에 도달하지 못했습니다.",
                "",
                "## 실패 섹션",
                *failed_sections,
                "",
                "## 반복 실패 패턴",
                "- 요구사항, 아키텍처 또는 실패 모드 검토 중 하나 이상이 반복적으로 PASS 조건을 만족하지 못했습니다.",
                "",
                "## 안전하지 않은 가정",
                "- 사용자 확인 없이 구현 방향을 바꿀 수 있는 가정은 최종 명세로 승격하지 않았습니다.",
                "",
                "## 차단 질문",
                *(f"- {question}" for question in state.get("blocking_questions", [])),
                "",
                "## 실패한 영어 초안",
                "- `critical/FAILED_AGENT_SPEC_DRAFT.en.md`",
                "",
                "## 증거 요약",
                f"- 기록된 증거 수: {len(self.evidence.items)}",
                "",
                "이 보고서는 사용자에게 의사결정이 필요한 지점을 요약하며, 숨겨진 추론 원문은 포함하지 않습니다.",
            ]
        )
