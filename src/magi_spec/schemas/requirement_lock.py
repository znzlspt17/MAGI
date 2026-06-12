"""Requirement Lock Sheet schema for v2 pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


VALID_REQUEST_TYPES = {"product", "feature", "bugfix", "refactor", "infra"}
VALID_RISK_LEVELS = {"low", "medium", "high"}


@dataclass(slots=True)
class RequirementItem:
    id: str
    text: str
    source: str = "user_request"  # user_request|user_answer|assumption|web_evidence

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "text": self.text, "source": self.source}

    @classmethod
    def from_dict(cls, data: Any) -> "RequirementItem":
        if not isinstance(data, dict):
            return cls(id="REQ-UNK", text=str(data or ""), source="user_request")
        return cls(
            id=str(data.get("id", "REQ-UNK")),
            text=str(data.get("text", "")),
            source=str(data.get("source", "user_request")),
        )


@dataclass(slots=True)
class QAItem:
    question_id: str
    question: str
    answer: str

    def to_dict(self) -> dict[str, str]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "answer": self.answer,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "QAItem":
        if not isinstance(data, dict):
            return cls(question_id="Q-UNK", question="", answer="")
        return cls(
            question_id=str(data.get("question_id", "Q-UNK")),
            question=str(data.get("question", "")),
            answer=str(data.get("answer", "")),
        )


@dataclass(slots=True)
class AssumptionItem:
    id: str
    text: str
    risk: str = "low"  # low|medium|high

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "text": self.text, "risk": self.risk}

    @classmethod
    def from_dict(cls, data: Any) -> "AssumptionItem":
        if not isinstance(data, dict):
            return cls(id="ASM-UNK", text=str(data or ""), risk="low")
        raw_risk = str(data.get("risk", "low")).lower()
        return cls(
            id=str(data.get("id", "ASM-UNK")),
            text=str(data.get("text", "")),
            risk=raw_risk if raw_risk in VALID_RISK_LEVELS else "low",
        )


@dataclass(slots=True)
class RequirementLockSheet:
    lock_id: str
    request_type: str  # product|feature|bugfix|refactor|infra
    request_summary: str
    user_answers: list[QAItem] = field(default_factory=list)
    mandatory_requirements: list[RequirementItem] = field(default_factory=list)
    recommended_requirements: list[RequirementItem] = field(default_factory=list)
    optional_requirements: list[RequirementItem] = field(default_factory=list)
    non_scope: list[RequirementItem] = field(default_factory=list)
    assumptions: list[AssumptionItem] = field(default_factory=list)
    constraints: list[RequirementItem] = field(default_factory=list)
    acceptance_criteria_seed: list[str] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lock_id": self.lock_id,
            "request_type": self.request_type,
            "request_summary": self.request_summary,
            "user_answers": [a.to_dict() for a in self.user_answers],
            "mandatory_requirements": [r.to_dict() for r in self.mandatory_requirements],
            "recommended_requirements": [r.to_dict() for r in self.recommended_requirements],
            "optional_requirements": [r.to_dict() for r in self.optional_requirements],
            "non_scope": [r.to_dict() for r in self.non_scope],
            "assumptions": [a.to_dict() for a in self.assumptions],
            "constraints": [r.to_dict() for r in self.constraints],
            "acceptance_criteria_seed": list(self.acceptance_criteria_seed),
            "unresolved_questions": list(self.unresolved_questions),
            "source_refs": list(self.source_refs),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RequirementLockSheet":
        def _req_list(key: str) -> list[RequirementItem]:
            return [RequirementItem.from_dict(i) for i in data.get(key, []) if i]

        def _asm_list(key: str) -> list[AssumptionItem]:
            return [AssumptionItem.from_dict(i) for i in data.get(key, []) if i]

        def _qa_list(key: str) -> list[QAItem]:
            return [QAItem.from_dict(i) for i in data.get(key, []) if i]

        def _str_list(key: str) -> list[str]:
            return [str(i) for i in data.get(key, []) if str(i).strip()]

        raw_type = str(data.get("request_type", "feature"))
        return cls(
            lock_id=str(data.get("lock_id", f"lock_{uuid4().hex[:8]}")),
            request_type=raw_type if raw_type in VALID_REQUEST_TYPES else "feature",
            request_summary=str(data.get("request_summary", "")),
            user_answers=_qa_list("user_answers"),
            mandatory_requirements=_req_list("mandatory_requirements"),
            recommended_requirements=_req_list("recommended_requirements"),
            optional_requirements=_req_list("optional_requirements"),
            non_scope=_req_list("non_scope"),
            assumptions=_asm_list("assumptions"),
            constraints=_req_list("constraints"),
            acceptance_criteria_seed=_str_list("acceptance_criteria_seed"),
            unresolved_questions=_str_list("unresolved_questions"),
            source_refs=_str_list("source_refs"),
        )

    def to_markdown(self) -> str:
        """Generate Korean Markdown summary for analysis/requirement_lock_sheet.ko.md."""
        lines = [
            "# 요구사항 잠금 시트",
            "",
            f"- **잠금 ID**: {self.lock_id}",
            f"- **요청 유형**: {self.request_type}",
            f"- **요청 요약**: {self.request_summary}",
            "",
        ]
        if self.user_answers:
            lines += ["## 사용자 답변", ""]
            for qa in self.user_answers:
                lines += [f"**{qa.question}**", f"> {qa.answer}", ""]

        if self.mandatory_requirements:
            lines += ["## 필수 요구사항 (Mandatory)", ""]
            for r in self.mandatory_requirements:
                lines.append(f"- [{r.id}] {r.text}")
            lines.append("")

        if self.non_scope:
            lines += ["## 비범위 (Out of Scope)", ""]
            for r in self.non_scope:
                lines.append(f"- [{r.id}] {r.text}")
            lines.append("")

        if self.assumptions:
            lines += ["## 가정 (Assumptions)", ""]
            for a in self.assumptions:
                lines.append(f"- [{a.id}][{a.risk}] {a.text}")
            lines.append("")

        if self.acceptance_criteria_seed:
            lines += ["## 완료 기준 씨앗 (Acceptance Criteria Seed)", ""]
            for s in self.acceptance_criteria_seed:
                lines.append(f"- {s}")
            lines.append("")

        if self.unresolved_questions:
            lines += ["## 미해결 질문", ""]
            for q in self.unresolved_questions:
                lines.append(f"- {q}")
            lines.append("")

        return "\n".join(lines)

    @classmethod
    def build_fallback(
        cls,
        *,
        request_type: str = "feature",
        request_summary: str = "",
        blocking_questions: list[str] | None = None,
        assumptions: list[str] | None = None,
    ) -> "RequirementLockSheet":
        """Build a minimal sheet when LLM parsing fails."""
        return cls(
            lock_id=f"lock_{uuid4().hex[:8]}",
            request_type=request_type if request_type in VALID_REQUEST_TYPES else "feature",
            request_summary=request_summary or "사용자 요청 기반 명세 생성",
            mandatory_requirements=[
                RequirementItem(
                    id="REQ-001",
                    text="Implement only the behavior explicitly requested by the user.",
                    source="user_request",
                ),
            ],
            non_scope=[
                RequirementItem(
                    id="NS-001",
                    text="MAGI does not implement the target project directly.",
                    source="system",
                ),
                RequirementItem(
                    id="NS-002",
                    text="Do not run Codex, Copilot, Cursor, Claude Code, or any implementation agent.",
                    source="system",
                ),
            ],
            assumptions=[
                AssumptionItem(
                    id="ASM-001",
                    text=a,
                    risk="low",
                )
                for a in (assumptions or [
                    "사용자가 명시하지 않은 세부 구현 방식은 기존 프로젝트 관례를 우선한다.",
                    "최종 산출물은 구현 에이전트가 바로 사용할 수 있는 영어 Markdown 명세다.",
                ])
            ],
            unresolved_questions=list(blocking_questions or []),
            acceptance_criteria_seed=[
                "Final spec includes scope, forbidden behaviors, acceptance criteria, and test plan.",
            ],
            source_refs=["raw/user_request.md"],
        )
