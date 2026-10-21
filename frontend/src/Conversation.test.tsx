import { afterEach, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Conversation } from "./Conversation";

vi.mock("./QuestionActions", () => ({ QuestionActions: () => null, questionDetails: (label: string) => ({ label }) }));
afterEach(cleanup);

it("답변 아래 질문 참조를 독립적으로 클릭과 키보드로 펼친다", async () => {
  const user = userEvent.setup();
  render(<Conversation job={{ id: "job", status: "completed", session_events: [{ id: "e", action: "answer", input: { answers: [
    { question_id: "A", question: "첫 질문 원문", answer: "첫 답변\n다음 줄" },
    { question_id: "B", question: "둘째 질문 원문", answer: "둘째 답변" },
    { question_id: "C", answer: "질문 없는 답변" },
  ] } }] }} select={vi.fn()} onAction={vi.fn()} busy={false} />);
  const triggers = screen.getAllByRole("button", { name: "답변 대상 질문" });
  expect(triggers).toHaveLength(2);
  expect(triggers.every(trigger => trigger.getAttribute("aria-expanded") === "false")).toBe(true);
  expect(screen.queryByText("첫 질문 원문")).not.toBeInTheDocument();
  expect(screen.getByText("첫 답변 다음 줄").textContent).toBe("첫 답변\n다음 줄");
  expect(screen.getByText("질문 없는 답변")).toBeVisible();
  await user.click(triggers[0]);
  expect(triggers[0]).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("첫 질문 원문")).toBeVisible();
  expect(triggers[1]).toHaveAttribute("aria-expanded", "false");
  triggers[1].focus();
  await user.keyboard("{Enter}");
  expect(screen.getByText("둘째 질문 원문")).toBeVisible();
  expect(within(triggers[1].parentElement!).getByText("둘째 질문 원문")).toBeVisible();
  await user.keyboard(" ");
  expect(triggers[1]).toHaveAttribute("aria-expanded", "false");
});
