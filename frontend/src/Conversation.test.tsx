import { afterEach, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Conversation } from "./Conversation";

vi.mock("./Auth", () => ({ useAuth: () => ({ publicMode: false, user: null, status: {} }) }));
afterEach(cleanup);
it('질문 답변 중에는 추가 의견을 접고 초안과 키보드 접근을 유지한다',async()=>{
 const user=userEvent.setup();sessionStorage.clear();
 render(<Conversation job={{id:'compact',status:'NEEDS_USER_INPUT',state:{blocking_questions:['[Q] 사용할 사람'],plan:{goal:'요청 확인'},allowed_actions:['message']}}} select={vi.fn()} onAction={vi.fn()} busy={false}/>);
 const toggle=screen.getByRole('button',{name:'수정 의견 또는 추가 요청'});
 expect(screen.queryByRole('textbox',{name:'수정 의견 또는 추가 요청'})).toBeNull();
 toggle.focus();await user.keyboard('{Enter}');
 await user.type(screen.getByRole('textbox',{name:'수정 의견 또는 추가 요청'}),'보관 30일');
 await user.click(toggle);await user.click(toggle);
 expect(screen.getByRole('textbox',{name:'수정 의견 또는 추가 요청'})).toHaveValue('보관 30일');
 sessionStorage.clear();
});

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

it('현재 질문은 대화 안에 한 번만 표시하고 제출 컨트롤은 하단에 둔다',async()=>{
 const user=userEvent.setup();
 const job={id:'inline-questions',status:'NEEDS_USER_INPUT',state:{blocking_questions:['[A] 사용할 사람','[B] 사용할 환경']},session_events:[{id:'e',action:'generate',summary:'두 가지를 확인해주세요.',questions:['[A] 사용할 사람','[B] 사용할 환경']}]};
 const view=render(<Conversation job={job} select={vi.fn()} onAction={vi.fn()} busy={false}/>);
 const body=view.container.querySelector('.chat-viewport') as HTMLElement;
 const footer=view.container.querySelector('.chat-actions') as HTMLElement;
 expect(within(body).getAllByRole('textbox')).toHaveLength(2);
 expect(within(footer).queryByRole('textbox')).toBeNull();
 expect(within(footer).getByRole('button',{name:'답변 제출'})).toBeVisible();
 await user.type(within(body).getByRole('textbox',{name:'사용할 사람'}),'팀원');
 expect(within(footer).getByText('답변 1/2개 작성')).toBeVisible();
 view.rerender(<Conversation job={{...job,message:'새로운 상태'}} select={vi.fn()} onAction={vi.fn()} busy={false}/>);
 expect(screen.getByRole('textbox',{name:'사용할 사람'})).toHaveValue('팀원');
});
