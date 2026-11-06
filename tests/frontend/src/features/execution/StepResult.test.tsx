import "@testing-library/jest-dom/vitest";
import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StepResult } from "@/features/workspace/Workspace";

afterEach(cleanup);

it("명세 생성 안의 검토 기준 실패와 보정 횟수를 기본 화면에 표시한다", () => {
  render(<StepResult node={{ id: "failed", stage: "spec_compile", status: "failed" }} detail={{ result: { diagnostic: {
    error_stage: "rubric_generate", validation_reason: "basis_quote_not_found", context: { requirement_id: "REQ-1" },
    attempts: [1, 2, 3, 4].map(attempt => ({ attempt })),
  } } }} />);
  expect(screen.getByText(/실패 단계:/).parentElement).toHaveTextContent("검토 기준 생성");
  expect(screen.getByText(/검토 기준의 근거 인용을 확정 요구사항에서 찾지 못했습니다/)).toBeVisible();
  expect(screen.getByText("요구사항 참조: REQ-1")).toBeVisible();
  expect(screen.getByText(/검증 4회 · 자동 보정 3회/)).toBeVisible();
  expect(screen.queryByText("상세 결과 기록 없음")).not.toBeInTheDocument();
});

it("불완전한 과거 보정 기록의 횟수를 추측하지 않는다", () => {
  render(<StepResult node={{ id: "failed", status: "failed" }} detail={{ result: { diagnostic: {
    attempts: [{ attempt: 2 }],
  } } }} />);
  expect(screen.queryByText(/검증 \d+회 · 자동 보정/)).not.toBeInTheDocument();
  expect(screen.getByText(/검증 및 자동 보정 횟수를 확인할 수 없습니다/)).toBeVisible();
});

it("현재 실행의 서버 재시도 판정과 호출 반복 가능성을 표시한다", () => {
  const detail = { result: { diagnostic: { validation_reason: "basis_reference_invalid" } } };
  const view = render(<StepResult node={{ id: "failed", status: "failed" }} detail={detail} retry={{ can_retry: true }} />);
  expect(screen.getByText(/저장된 답변을 유지하고 다시 시도할 수 있습니다/)).toBeVisible();
  view.rerender(<StepResult node={{ id: "failed", status: "failed" }} detail={detail} retry={{ can_retry: true, retry_requires_replay: true }} />);
  expect(screen.getByText(/호출 반복 가능성 확인 후 다시 시도할 수 있습니다/)).toBeVisible();
  view.rerender(<StepResult node={{ id: "failed", status: "failed" }} detail={detail} retry={{ can_retry: false, retry_unavailable_reason: "저장된 기록이 없습니다." }} />);
  expect(screen.getByText(/저장된 기록이 없습니다/)).toBeVisible();
});

it("진단이 있는 실패에 관례적인 요약이 있더라도 빈 결과 문구를 표시하지 않는다", () => {
  render(<StepResult node={{ id: "failed", status: "failed", summary: "사용자 작업을 접수했습니다." }} detail={{ result: {
    diagnostic: { validation_reason: "basis_quote_not_found" },
  } }} />);
  expect(screen.queryByText("상세 결과 기록 없음")).not.toBeInTheDocument();
});

it("루브릭 생성 상태와 항목별 판정 집계를 표시한다", () => {
  render(<StepResult node={{ id: "review", stage: "checklist_critic" }} detail={{ result: {
    rubric_summary: { status: "evaluated", policy_version: 1, item_count: 4, PASS: 2, FAIL: 1, UNDETERMINED: 1 },
  } }} />);
  expect(screen.getByText("검사 기준 4개 · 평가 완료")).toBeVisible();
  expect(screen.getByText("충족 2 · 미충족 1 · 판단 불가 1")).toBeVisible();
});

it("작업 계획의 목표·판단 근거·대상·예상 결과를 표시한다", () => {
  render(<StepResult node={{ id: "plan", stage: "planner", title: "작업 계획" }} detail={{ result: { plan: {
    goal: "무기 정책 반영", reason: "이미 확인한 답변을 반영합니다.", target: "보스 격파 후 무기 유지",
    expected_result: "수정된 초안", tasks: [{ id: "fix", title: "기존 답변 반영", status: "pending" }],
  } } }} />);
  expect(screen.getByText("이미 확인한 답변을 반영합니다.")).toBeVisible();
  expect(screen.getByText("보스 격파 후 무기 유지")).toBeVisible();
  expect(screen.getByText("수정된 초안")).toBeVisible();
  expect(screen.getByText("기존 답변 반영 · 예정")).toBeVisible();
});

it("과거 계획 기록이 없는 경우 명시하고 해결 판단의 다음 행동을 표시한다", () => {
  const view = render(<StepResult node={{ id: "old", stage: "planner" }} detail={{ result: {} }} />);
  expect(screen.getByText("당시 작업 계획의 상세 내용이 저장되지 않았습니다.")).toBeVisible();
  view.rerender(<StepResult node={{ id: "review", stage: "review_resolution" }} detail={{ result: { action: "repair" } }} />);
  expect(screen.getByText("초안 수정·재검토")).toBeVisible();
});

it("실패 단계의 안전한 진단 코드와 중단 사유를 표시한다", async () => {
  render(<StepResult node={{ id: "failed", stage: "spec_compile", status: "failed" }} detail={{ result: {
    wait_reason: "초안 검증에 실패했습니다.", diagnostic: { error_code: "SPEC_COMPILATION_INVALID", error_stage: "spec_compile", failed_checks: ["spec_blocks"] },
  } }} />);
  await userEvent.click(screen.getByText("기술 진단 상세"));
  expect(screen.getByText("SPEC_COMPILATION_INVALID")).toBeVisible();
  expect(screen.getByText("검증 항목: spec_blocks")).toBeVisible();
  expect(screen.getByText("초안 검증에 실패했습니다.")).toBeVisible();
});

it("실패 사유와 복구 정보를 표시하고 과거 성공 요약을 숨긴다", async () => {
  const detail = { result: { diagnostic: { error_code: "REVIEW_VALIDATION_FAILED", error_stage: "checklist_critic",
    category: "response_invalid" as const, validation_reason: "rubric_evidence", failed_checks: ["rubric_evidence"],
    attempts: [{ attempt: 1, failed_checks: ["rubric_evidence"], validation_reason: "rubric_evidence" }] } } };
  render(<StepResult node={{ id: "failed", stage: "checklist_critic", status: "failed", summary: "검토 결과를 저장했습니다." }} detail={detail} />);
  expect(screen.queryByText("검토 결과를 저장했습니다.")).not.toBeInTheDocument();
  expect(screen.getAllByText(/검토 근거가 초안의 섹션 또는 인용과 일치하는지 확인하지 못했습니다/)[0]).toBeVisible();
  expect(screen.getByText(/검증되지 않은 검토 결과로 명세를 진행하지 않았습니다/)).toBeVisible();
  const toggle = screen.getByText("기술 진단 상세");
  expect(toggle.closest("details")).not.toHaveAttribute("open");
  await userEvent.click(toggle);
  expect(screen.getByText(/1회차/)).toBeVisible();
  expect(screen.getByText("REVIEW_VALIDATION_FAILED")).toBeVisible();
});

it("저장 누락과 응답 해석 문제를 구분한다", () => {
  render(<StepResult detail={{ recording_incomplete: true, response_incomplete: true }} />);
  expect(screen.getByText(/일부 상세 기록이 누락되었습니다/)).toBeVisible();
  expect(screen.getByText(/일부 응답을 해석하지 못했습니다/)).toBeVisible();
});

it("보정 후 성공한 단계는 과거 실패를 현재 작업 실패로 표시하지 않는다", async () => {
  render(<StepResult node={{ id: "review", stage: "checklist_critic", status: "completed" }} detail={{ result: { diagnostic: {
    attempts: [{ attempt: 1, failed_checks: ["rubric_evidence"], validation_reason: "quote_not_found" }],
  } } }} />);
  expect(screen.getByRole("region", { name: "보정 경과" })).toBeVisible();
  expect(screen.queryByRole("region", { name: "실패 진단" })).toBeNull();
  expect(screen.getByText("자동 보정 후 단계가 완료되었습니다.")).toBeVisible();
  await userEvent.click(screen.getByText("기술 진단 상세"));
  expect(screen.getByText(/1회차/)).toBeVisible();
});

it("불확실한 외부 호출에는 반복 동의 확인을 안내한다", () => {
  render(<StepResult node={{ id: "failed", status: "failed" }} detail={{ result: { diagnostic: { category: "execution_uncertain" } } }} />);
  expect(screen.getByText(/호출 반복에 대한 동의 여부를 확인하세요/)).toBeVisible();
});

it.each([
  ["response_invalid", "검증되지 않은 검토 결과로 명세를 진행하지 않았습니다.", "실행 이력에서 자동 보정 경과와 검증 실패 항목을 확인하세요."],
  ["prerequisite_stale", "현재 입력에 맞는 검토를 확인하기 전까지 작업을 중단했습니다.", "실행 이력에서 선행 자료와 복구 경과를 확인하세요."],
  ["execution_uncertain", "이전 외부 호출의 완료 여부를 확인하지 못해 자동 반복을 중단했습니다.", "호출 반복에 대한 동의 여부를 확인하세요."],
  ["persistence_failed", "처리 결과의 저장 완료 여부를 확인하지 못했습니다.", "실행 이력과 저장 상태를 확인하세요."],
] as const)("실패 분류 %s의 영향과 다음 확인을 함께 표시한다", (category, impact, next) => {
  render(<StepResult node={{ id: "failed", status: "failed" }} detail={{ result: { diagnostic: { category } } }} />);
  expect(screen.getByText(impact, { exact: false })).toBeVisible();
  expect(screen.getByText(next, { exact: false })).toBeVisible();
});

it("과거 진단에 분류가 없으면 영향은 추측하지 않고 기본 안내를 표시한다", () => {
  render(<StepResult node={{ id: "failed", status: "failed" }} detail={{ result: { diagnostic: { failed_checks: [] } } }} />);
  expect(screen.getByText(/상세 원인이 기록되지 않았거나 확인되지 않았습니다/)).toBeVisible();
  expect(screen.getByText(/실행 이력에서 실패 단계와 보정 경과를 확인하세요/)).toBeVisible();
  expect(screen.queryByText(/영향:/)).toBeNull();
});

it.each([
  ["requirement_unknown", "검토 기준이 참조한 요구사항을 확정 목록에서 찾지 못했습니다."],
  ["condition_missing", "검토 기준의 검사 조건을 확인하지 못했습니다."],
  ["importance_invalid", "검토 기준의 중요도가 해당 요구사항에 맞는지 확인하지 못했습니다."],
  ["basis_reference_invalid", "검토 기준의 근거가 해당 요구사항을 참조하는지 확인하지 못했습니다."],
  ["basis_quote_not_found", "검토 기준의 근거 인용을 확정 요구사항에서 찾지 못했습니다."],
  ["rubric_coverage_missing", "일부 필수 요구사항 또는 제약의 검토 기준을 찾지 못했습니다."],
])("검토 기준 오류 %s의 확인 실패 내용을 설명한다", (reason, expected) => {
  render(<StepResult node={{ id: "failed", status: "failed" }} detail={{ result: { diagnostic: {
    category: "response_invalid", failed_checks: ["rubric_basis"], validation_reason: reason,
  } } }} />);
  expect(screen.getByText(expected, { exact: false })).toBeVisible();
});


it("중단 원문 중복 없이 남은 결함과 다음 보완을 바로 표시한다", () => {
  render(<StepResult node={{ id: "stop", stage: "workflow", status: "blocked", summary: "한도 도달" }} detail={{ result: {
    wait_reason: "한도 도달", stop_diagnostic: {
      stop_reason: "repair_limit", cause: "실패 원인은 미확정입니다.", next_check: "초안과 대조해야 합니다.",
      issues: [{ issue_id: "I1", problem: "무기 정책 누락", required_change: "무기 유지 규칙 반영", resolution_kind: "auto_fix",
        attempts: [{ review_round: 1, proposed_change: "규칙 추가", outcome: "제안 이후 수정 여부는 확인되지 않습니다." }] }],
    },
  } }} />);
  expect(screen.getAllByText("한도 도달", { exact: false })).toHaveLength(1);
  expect(screen.getByText("무기 정책 누락")).toBeVisible();
  expect(screen.getByText("다음 보완: 무기 유지 규칙 반영")).toBeVisible();
  expect(screen.getByText("시스템 보완 대상")).toBeVisible();
  expect(screen.queryByRole("radio")).not.toBeInTheDocument();
});

it("과거 중단 기록 누락을 명시한다", () => {
  render(<StepResult detail={{ result: { stop_diagnostic: { recording_incomplete: true, issues: [] } } }} />);
  expect(screen.getByText(/보완 이력 기록이 부족합니다/)).toBeVisible();
});
