import { afterEach, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AgentPlan, AgentComposer } from "./AgentPlan";
import type { Job } from "./types";

vi.mock("./Auth", () => ({ useAuth: () => ({ publicMode: false, user: null, status: {} }) }));
afterEach(() => { cleanup(); sessionStorage.clear(); });
const job: Job = { id: "plan", status: "CRITICAL_BLOCKED", state: {
  revision: 1, allowed_actions: ["message", "retry"], wait_reason: "보관 기간을 확인해주세요.",
  plan: { goal: "메모 명세 보완", action: "blocked", reason: "보관 기간의 사용자 결정이 필요합니다.",
    tasks: [{ id: "retention", title: "보관 기간 확인", status: "blocked" }] },
} };

it("계획 이유와 대기 원인을 키보드로 펼쳐 확인한다", async () => {
  const user = userEvent.setup();
  render(<AgentPlan job={job} />);
  const summary = screen.getByText("현재 계획 · 메모 명세 보완");
  summary.focus(); await user.keyboard("{Enter}");
  expect(screen.getByText("보관 기간의 사용자 결정이 필요합니다.")).toBeVisible();
  expect(screen.getByRole("status")).toHaveTextContent("보관 기간을 확인해주세요.");
});

it("실행 중 초안을 보존하고 대기 후 자유 입력과 명시적인 추가 실행을 제출한다", async () => {
  const user = userEvent.setup(), action = vi.fn().mockResolvedValue(undefined);
  const view = render(<AgentComposer job={{ ...job, status: "running" }} onAction={action} busy={false} />);
  await user.type(screen.getByRole("textbox", { name: "수정 의견 또는 추가 요청" }), "보관 기간은 30일");
  expect(screen.getByRole("button", { name: "의견 보내기" })).toBeDisabled();
  view.rerender(<AgentComposer job={job} onAction={action} busy={false} />);
  await user.click(screen.getByRole("button", { name: "의견 보내기" }));
  expect(action).toHaveBeenLastCalledWith("message", "보관 기간은 30일");
  expect(screen.getByRole("textbox")).toHaveValue("");
  await user.click(screen.getByRole("button", { name: "저장된 결과로 추가 실행" }));
  expect(action).toHaveBeenLastCalledWith("retry", null);
});

it("제출 실패 시 작성 내용을 유지한다", async () => {
  const user = userEvent.setup(), action = vi.fn().mockRejectedValue(new Error("연결을 확인해주세요."));
  render(<AgentComposer job={job} onAction={action} busy={false} />);
  await user.type(screen.getByRole("textbox"), "초안 유지");
  await user.click(screen.getByRole("button", { name: "의견 보내기" }));
  expect(screen.getByRole("textbox")).toHaveValue("초안 유지");
  expect(screen.getByText("연결을 확인해주세요.")).toBeVisible();
});
