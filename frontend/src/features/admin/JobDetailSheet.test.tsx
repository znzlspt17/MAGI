import "@testing-library/jest-dom/vitest";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import JobDetailSheet from "./JobDetailSheet";
import type { JobDetail } from "./job-data";

afterEach(cleanup);
const props = { loading: false, error: "", tab: "history", setTab: vi.fn(), close: vi.fn(), retry: vi.fn(), restoreFocus: vi.fn() };
const job: JobDetail = { id: "one", session_events: [
  { id: "first", action: "generate", started_at: "2026-10-21T15:00:00Z", status: "NEEDS_USER_INPUT", summary: "요구사항을 확인했습니다", input: { request: "원래 요청\n다음 줄" }, questions: ["다음 질문"] },
  { id: "second", action: "answer", input: { answers: [{ question: "첫 질문", answer: "첫 답변" }, { answer: "둘째 답변" }] } },
  { id: "third", action: "approve" }, { id: "fourth", action: "unknown-action" },
] };

it("타임라인 요약과 원문 상세를 구분하고 독립적으로 펼친다", async () => {
  const user = userEvent.setup();
  render(<JobDetailSheet {...props} id="one" job={job} />);
  const timeline = within(screen.getByRole("list", { name: "실행별 처리 이력" }));
  expect(timeline.getByText("요구사항을 확인했습니다")).toBeVisible();
  expect(timeline.getByText(/26\. 10\. 22\..*KST/)).toBeVisible();
  const triggers = timeline.getAllByRole("button", { name: /상세 보기/ });
  expect(triggers.every(trigger => trigger.getAttribute("aria-expanded") === "false")).toBe(true);
  expect(screen.queryByText("원래 요청 다음 줄")).toBeNull();
  await user.click(triggers[0]);
  expect(screen.getByText("원래 요청 다음 줄").textContent).toBe("원래 요청\n다음 줄");
  expect(screen.getByText("다음 질문")).toBeVisible();
  triggers[1].focus(); await user.keyboard("{Enter}");
  expect(screen.getByText("첫 답변")).toBeVisible();
  expect(screen.getByText("둘째 답변")).toBeVisible();
  expect(screen.getByText("질문 원문 기록 없음")).toBeVisible();
  expect(triggers[0]).toHaveAttribute("aria-expanded", "true");
  await user.click(triggers[2]); expect(screen.getByText("사용자가 명세를 승인했습니다")).toBeVisible();
  await user.click(triggers[3]); expect(screen.getByText("기록된 동작: unknown-action")).toBeVisible();
});

it("재조회에는 펼침을 유지하고 다른 작업과 빈 이력을 안전하게 표시한다", async () => {
  const user = userEvent.setup();
  const view = render(<JobDetailSheet {...props} id="one" job={job} />);
  await user.click(screen.getByRole("button", { name: "1. 최초 요청 상세 보기" }));
  view.rerender(<JobDetailSheet {...props} id="one" job={null} loading />);
  view.rerender(<JobDetailSheet {...props} id="one" job={{ ...job }} />);
  expect(screen.getByRole("button", { name: "1. 최초 요청 상세 보기" })).toHaveAttribute("aria-expanded", "true");
  view.rerender(<JobDetailSheet {...props} id="two" job={{ ...job, id: "two" }} />);
  expect(screen.getByRole("button", { name: "1. 최초 요청 상세 보기" })).toHaveAttribute("aria-expanded", "false");
  expect(screen.getAllByText("시각 기록 없음")).toHaveLength(3);
  view.rerender(<JobDetailSheet {...props} id="empty" job={{ id: "empty", session_events: [] }} />);
  expect(screen.getByText("저장된 처리 이력이 없습니다.")).toBeVisible();
});
