import "@testing-library/jest-dom/vitest";
import { afterEach, expect, it, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ExecutionTimeline, ResearchResult } from "@/features/execution/ExecutionTimeline";
import type { Job, Step, ResearchRecord } from "@/shared/types";
afterEach(cleanup);
const job: Job = { id: "job", status: "completed", session_events: [
  { id: "first", action: "generate", questions: ["[Q1] 엔진은?"], summary: "질문을 준비했습니다" },
  { id: "last", action: "answer", input: { answers: [{ question_id: "Q1", question: "엔진은?", answer: "알맞게 선택" }] }, summary: "답변을 반영했습니다" },
] };
const nodes: Step[] = [{ id: "interview", execution_id: "first", stage: "interview", title: "요구사항 확인", status: "completed" }, { id: "waiting", execution_id: "first", stage: "await_user", title: "요구사항 확인 필요", status: "waiting" }];
it("사용자 작업 노드가 없어도 실행 입력의 최초 요구사항과 질문 답변을 표시한다", async () => {
  const user = userEvent.setup();
  render(<ExecutionTimeline job={{ ...job, session_events: [
    { ...job.session_events![0], input: { request: "오프라인 메모 앱" }, started_at: "2026-11-03T00:00:00Z" },
    job.session_events![1],
  ] }} nodes={nodes} selected="" select={vi.fn()} />);
  expect(screen.getByText("엔진은?", { exact: true })).toBeVisible();
  expect(screen.getByText("알맞게 선택")).toBeVisible();
  await user.click(screen.getByRole("button", { name: /1. 최초 요청/ }));
  expect(screen.getByText("오프라인 메모 앱")).toBeVisible();
  expect(screen.queryByText("저장된 사용자 입력이 없습니다.")).toBeNull();
  expect(screen.getAllByText("시각 기록 없음")).toHaveLength(1);
  expect(screen.getByText(/\(KST\)/)).toBeVisible();
});
it("실행별 펼침과 원본 단계 선택을 유지하고 질문·답변을 구분한다", async () => {
  const user = userEvent.setup(), select = vi.fn();
  const view = render(<ExecutionTimeline job={job} nodes={nodes} selected="waiting" select={select} />);
  expect(screen.getByText("알맞게 선택")).toBeVisible();
  expect(screen.queryByRole("button", { name: "요구사항 확인 · 완료" })).toBeNull();
  await user.click(screen.getByRole("button", { name: /1. 최초 요청/ }));
  expect(screen.getByText("요구사항 확인 · 답변 대기")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "하위 처리 단계 2개" }));
  await user.click(screen.getByRole("button", { name: "요구사항 확인 필요 · 답변 필요" }));
  expect(select).toHaveBeenCalledWith("waiting");
  view.rerender(<ExecutionTimeline job={{ ...job }} nodes={[...nodes]} selected="waiting" select={select} />);
  expect(screen.getByRole("button", { name: /1. 최초 요청/ })).toHaveAttribute("aria-expanded", "true");
});
it("검색 링크와 원문 검토를 구분하고 안전한 URL만 연결한다", () => {
  const research: ResearchRecord = { mode: "auto", performed: true, outcome: "links_found", reason: "search_results", query: "문서", retrieved_at: "2026-10-22T00:00:00Z", result_count: 2, sources: [{ title: "공식 문서", url: "https://example.com/docs" }, { title: "잘못된 링크", url: "javascript:alert(1)" }] };
  const view = render(<ResearchResult research={research} />);
  expect(screen.getAllByRole("link")).toHaveLength(1);
  expect(screen.getByText(/원문을 읽고 검토한 근거는 아닙니다/)).toBeVisible();
  view.rerender(<ResearchResult />);
  expect(screen.getByText("당시 조사 상세가 저장되지 않았습니다.")).toBeVisible();
});

it("31개 단계 중 선택한 행 바로 아래에 상세를 표시하고 전환한다", async () => {
  const user = userEvent.setup(), select = vi.fn();
  const steps: Step[] = Array.from({ length: 31 }, (_, i) => ({ id: `step-${i}`, execution_id: "last", stage: "planner", title: `작업 계획 ${i + 1}`, status: "completed" }));
  const view = render(<ExecutionTimeline job={job} nodes={steps} selected="step-0" select={select} detail={<p>첫 번째 판단 근거</p>} />);
  await user.click(screen.getByRole("button", { name: "하위 처리 단계 31개" }));
  const first = screen.getByRole("button", { name: "작업 계획 1 · 완료" });
  expect(first.nextElementSibling).toHaveTextContent("첫 번째 판단 근거");
  await user.click(screen.getByRole("button", { name: "작업 계획 31 · 완료" }));
  expect(select).toHaveBeenCalledWith("step-30");
  view.rerender(<ExecutionTimeline job={job} nodes={steps} selected="step-30" select={select} detail={<p>마지막 판단 근거</p>} />);
  expect(screen.queryByText("첫 번째 판단 근거")).toBeNull();
  expect(screen.getByRole("button", { name: "작업 계획 31 · 완료" }).nextElementSibling).toHaveTextContent("마지막 판단 근거");
});
