"""검증된 검토 기록으로 중단 진단을 계산한다."""
from __future__ import annotations

from collections import Counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from backend.services.issue_identity import defect_key


class RecordModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


class ReviewIssue(RecordModel):
    issue_id: str = ""
    requirement_id: str | None = None
    decision_key: str = ""
    checklist_id: str = ""
    severity: str = ""
    status: str = ""
    problem: str = ""
    required_change: str = ""
    resolution_reason: str = ""
    resolution_kind: str = ""
    basis_refs: list[str] = Field(default_factory=list)
    decision_answer_id: str | None = None

    @property
    def identity(self) -> str:
        return defect_key(self.requirement_id, self.decision_key, self.checklist_id)

    @property
    def unresolved(self) -> bool:
        return self.status != "resolved" and (self.severity in {"major", "blocking"}
            or self.resolution_kind == "user_decision" or bool(self.decision_answer_id))


class ReviewRound(RecordModel):
    review_round: int = 0
    draft_hash: str = ""
    issues: list[ReviewIssue] = Field(default_factory=list)


class CompletedTask(RecordModel):
    action: str = ""
    status: str = ""


class DiagnosticInput(RecordModel):
    stop_reason: str = ""
    structured_issues: list[ReviewIssue] | None = None
    issues: list[ReviewIssue] | None = None
    resolution_history: list[ReviewRound] = Field(default_factory=list)
    task_results: list[CompletedTask] = Field(default_factory=list)

    @property
    def current_issues(self) -> list[ReviewIssue]:
        if self.structured_issues is not None:
            return self.structured_issues
        if self.issues is not None:
            return self.issues
        return self.resolution_history[-1].issues if self.resolution_history else []


class RepairAttempt(RecordModel):
    review_round: int
    proposed_change: str
    outcome: str


class DiagnosticIssue(RecordModel):
    issue_id: str = ""
    requirement_id: str | None = None
    problem: str = ""
    required_change: str = ""
    resolution_reason: str = ""
    resolution_kind: str = ""
    basis_refs: list[str] = Field(default_factory=list)
    decision_answer_id: str | None = None
    attempts: list[RepairAttempt] = Field(default_factory=list)


class WorkCount(RecordModel):
    action: str
    count: int


class StopDiagnostic(RecordModel):
    stop_reason: str
    issues: list[DiagnosticIssue]
    completed_work: list[WorkCount]
    cause: str
    next_check: str
    recording_incomplete: bool
    work_scope: str = "job"


def parse_diagnostic_input(value: dict[str, Any]) -> tuple[DiagnosticInput, bool]:
    # 훼손된 선택 필드는 부분 기록으로 표시하고, 다른 검증된 근거는 보존한다.
    accepted: dict[str, Any] = {}
    incomplete = False
    for key in DiagnosticInput.model_fields:
        if key not in value:
            continue
        try:
            DiagnosticInput.model_validate({key: value[key]})
        except ValidationError:
            incomplete = True
            # 최신 목록이 훼손된 경우 과거 검토를 현재 결함으로 되살리지 않는다.
            if key in {"structured_issues", "issues"}:
                accepted[key] = []
        else:
            accepted[key] = value[key]
    return DiagnosticInput.model_validate(accepted), incomplete


def saved_diagnostic(value: object) -> StopDiagnostic | None:
    try:
        return StopDiagnostic.model_validate(value)
    except ValidationError:
        return None


def repair_attempts(issue: ReviewIssue, history: list[ReviewRound]) -> list[RepairAttempt]:
    attempts = []
    for index, record in enumerate(history):
        previous = next((item for item in record.issues if item.identity == issue.identity), None)
        if previous is None:
            continue
        reviewed = next((entry for entry in history[index + 1:]
                         if entry.draft_hash and record.draft_hash and entry.draft_hash != record.draft_hash), None)
        outcome = "제안 이후 수정·재검토 여부는 기록으로 확인되지 않습니다."
        if reviewed is not None:
            match = next((item for item in reviewed.issues if item.identity == issue.identity), None)
            outcome = ("다른 초안의 재검토에서도 같은 결함이 지적됐습니다."
                       if match is not None and match.status != "resolved" else
                       "다음 초안에는 같은 미해결 지적이 기록되지 않았습니다. 해소 여부는 확정할 수 없습니다.")
        attempts.append(RepairAttempt(review_round=record.review_round or index + 1,
                                      proposed_change=previous.required_change, outcome=outcome))
    return attempts


def diagnose(source: DiagnosticInput, *, incomplete: bool = False) -> StopDiagnostic:
    issues = [DiagnosticIssue(**issue.model_dump(include=set(DiagnosticIssue.model_fields) - {"attempts"}),
                              attempts=repair_attempts(issue, source.resolution_history))
              for issue in source.current_issues if issue.unresolved]
    counts = Counter(task.action for task in source.task_results if task.status == "completed")
    return StopDiagnostic(
        stop_reason=source.stop_reason, issues=issues,
        completed_work=[WorkCount(action=action, count=counts[action])
                        for action in ("spec_compile", "checklist_critic", "review_resolution") if counts[action]],
        cause="실패 원인은 미확정입니다. 검토 기록만으로 수정 미반영인지, 반영 후에도 불충분했는지 단정할 수 없습니다.",
        next_check="다음 보완에서는 지적 위치와 최신 초안을 대조해 제안한 수정의 반영 여부와 재검토 결과를 확인해야 합니다.",
        recording_incomplete=incomplete or not source.resolution_history or not issues,
    )


def stop_diagnostic(state: dict[str, Any]) -> dict[str, Any]:
    source, incomplete = parse_diagnostic_input(state)
    return diagnose(source, incomplete=incomplete).model_dump()
