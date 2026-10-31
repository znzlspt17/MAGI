import "@testing-library/jest-dom/vitest";
import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { StepResult } from "./Workspace";

afterEach(cleanup);

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

it("실패 단계의 안전한 진단 코드와 중단 사유를 표시한다", () => {
  render(<StepResult node={{ id: "failed", stage: "spec_compile", status: "failed" }} detail={{ result: {
    wait_reason: "초안 검증에 실패했습니다.", diagnostic: { error_code: "SPEC_COMPILATION_INVALID", error_stage: "spec_compile", failed_checks: ["spec_blocks"] },
  } }} />);
  expect(screen.getByText("SPEC_COMPILATION_INVALID")).toBeVisible();
  expect(screen.getByText("검증 항목: spec_blocks")).toBeVisible();
  expect(screen.getByText("초안 검증에 실패했습니다.")).toBeVisible();
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
