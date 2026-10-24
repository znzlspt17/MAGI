"""화면·gateway·backend가 공유하는 작업 명령 계약."""

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, model_validator


CommandKind = Literal[
    "generate", "answer", "message", "revise", "approve", "retry", "continue", "stop"
]
COMMAND_KINDS = frozenset(get_args(CommandKind))


class JobCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: CommandKind
    job_id: str | None = None
    execution_id: str | None = None
    candidate_hash: str | None = None
    input: Any = None
    project_id: str | None = None
    decision_reuse: list[dict] | None = None

    @model_validator(mode="after")
    def target(self):
        if self.kind == "generate":
            if (
                self.job_id is not None
                or self.execution_id is not None
                or self.candidate_hash is not None
            ):
                raise ValueError("새 작업에는 이전 실행을 지정할 수 없습니다.")
        elif not self.job_id or not self.execution_id:
            raise ValueError("현재 작업과 실행 식별값이 필요합니다.")
        if self.kind == "approve" and not self.candidate_hash:
            raise ValueError("승인할 문서 버전이 필요합니다.")
        if self.kind != "generate" and (
            self.project_id is not None or self.decision_reuse is not None
        ):
            raise ValueError("공통 결정 선택은 새 작업에만 사용할 수 있습니다.")
        if self.kind in {"generate", "message", "revise", "continue"} and (
            not isinstance(self.input, str)
            or not self.input.strip()
            or len(self.input) > 20000
        ):
            raise ValueError("작업 입력은 1~20,000자 문자열이어야 합니다.")
        if self.kind == "answer" and (
            not isinstance(self.input, list)
            or not self.input
            or len(self.input) > 100
            or any(not isinstance(item, dict) for item in self.input)
        ):
            raise ValueError("답변은 비어 있지 않은 목록이어야 합니다.")
        if self.kind in {"approve", "retry", "stop"} and self.input is not None:
            raise ValueError("승인과 재개에는 추가 입력을 지정할 수 없습니다.")
        return self

    def parameters(self):
        if self.kind == "generate":
            return {
                "request": self.input,
                "project_id": self.project_id,
                "decision_reuse": self.decision_reuse,
            }
        return {
            "id": self.job_id,
            "execution_id": self.execution_id,
            "candidate_hash": self.candidate_hash,
            "payload": self.input,
        }
