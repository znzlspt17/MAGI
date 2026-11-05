import { afterEach, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Conversation } from "@/features/conversation/Conversation";
import type { Job } from "@/shared/types";

vi.mock("@/features/auth/Auth", () => ({ useAuth: () => ({ publicMode: false, user: null, status: {} }) }));
vi.mock("@/features/requirements/RequirementReview", () => ({ RequirementReview: () => null }));
afterEach(cleanup);
it("현재 실패의 동일한 구조화 진단을 대화에 표시한다", async () => {
  const job: Job = { id: "failed-job", status: "error", execution_id: "e1", state: {},
    execution_graph: { nodes: [{ id: "failed", execution_id: "e1", stage: "workflow", status: "failed" }] } };
  render(<Conversation job={job} select={vi.fn()} onAction={vi.fn()} busy={false} failureDetail={{ result: { diagnostic: {
    category: "response_invalid", error_stage: "checklist_critic", error_code: "REVIEW_VALIDATION_FAILED", validation_reason: "rubric_evidence",
  } } }} />);
  expect(screen.getByText(/검토 근거가 초안의 섹션 또는 인용과 일치하는지 확인하지 못했습니다/)).toBeVisible();
  await userEvent.click(screen.getByText("기술 진단 상세"));
  expect(screen.getByText("REVIEW_VALIDATION_FAILED")).toBeVisible();
});
it("실패 상세 조회 자체가 실패하면 대화에서 알린다", () => {
  render(<Conversation job={{ id: "failure-load", status: "error" }} select={vi.fn()} onAction={vi.fn()} busy={false}
    failureDetail={{ unavailable: true, message: "요청 실패" }} />);
  expect(screen.getByText(/실패 상세를 불러오지 못했습니다/)).toBeVisible();
});
it("대화에서 기록 누락과 응답 해석 실패를 각각 알린다", () => {
  render(<Conversation job={{ id: "failure-incomplete", status: "error" }} select={vi.fn()} onAction={vi.fn()} busy={false}
    failureDetail={{ recording_incomplete: true, response_incomplete: true }} />);
  expect(screen.getByText(/일부 상세 기록이 누락되었습니다/)).toBeVisible();
  expect(screen.getByText(/일부 응답을 해석하지 못했습니다/)).toBeVisible();
});
const proposalJob = (planned: boolean, id = "proposal"): Job => ({ id, status: "PASS_PENDING_USER_APPROVAL",
  state: { status: "PASS_PENDING_USER_APPROVAL", allowed_actions: ["message", "approve"], ...(planned ? { plan: { goal: "검토" } } : {}) },
  change_review: { status: "complete", after_hash: "candidate", analysed: 1, remaining: 0, sources: [], changes: [{
    id: "C", change: "modified", before: null, after: null, status: "analysed", reason: "", question: "버전을 지정할까요?",
    question_form: { question_id: "C", question: "버전을 지정할까요?", form_version: "v1", input_type: "single_choice",
      options: [{ id: "keep", label: "미정으로 유지" }, { id: "set", label: "버전 지정" }] },
  }] } });

it.each([true, false])("계획형=%s 제안 답변은 보이는 초안에 추가하고 하단 전송에서만 제출한다", async planned => {
  sessionStorage.clear();
  const user = userEvent.setup(), action = vi.fn().mockResolvedValue(undefined);
  const job = proposalJob(planned);
  const inputName = planned ? "수정 의견 또는 추가 요청" : "수정 의견 보내기";
  const view = render(<Conversation job={job} select={vi.fn()} onAction={action} busy={false} />);
  const input = screen.getByRole("textbox", { name: inputName });
  await user.type(input, "기존 의견");
  await user.click(screen.getByRole("radio", { name: "버전 지정" }));
  expect(action).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "이 명세 승인" })).toBeEnabled();
  await user.type(screen.getByRole("textbox", { name: /추가 설명/ }), "Unity 6");
  await user.click(screen.getByRole("button", { name: "답변을 수정 의견에 추가" }));
  const expected = "기존 의견\n\n확인 제안: 버전을 지정할까요?\n답변: 버전 지정\n추가 설명: Unity 6";
  expect(input).toHaveValue(expected);
  expect(input).toHaveFocus();
  expect(sessionStorage.getItem(`draft:local:proposal:${planned ? "message" : "feedback"}`)).toBe(expected);
  expect(action).not.toHaveBeenCalled();
  view.rerender(<Conversation job={{ ...job, change_review: { ...job.change_review!, after_hash: "next" } }} select={vi.fn()} onAction={action} busy={false} />);
  expect(screen.getByRole("textbox", { name: inputName })).toHaveValue(expected);
  expect(screen.getByRole("radio", { name: "버전 지정" })).not.toBeChecked();
  await user.click(screen.getByRole("button", { name: planned ? "의견 보내기" : "수정 요청" }));
  expect(action).toHaveBeenCalledExactlyOnceWith(planned ? "message" : "revise", expected);
  expect(screen.getByRole("textbox", { name: inputName })).toHaveValue("");
});

it("계획형 초안과 선택은 작업별로 분리하고 읽기 전용에서는 추가를 막는다", async () => {
  sessionStorage.clear();
  const user = userEvent.setup();
  const first = proposalJob(true), second = proposalJob(true, "other");
  const view = render(<Conversation job={first} select={vi.fn()} onAction={vi.fn()} busy={false} />);
  await user.type(screen.getByRole("textbox", { name: "수정 의견 또는 추가 요청" }), "첫 작업");
  await user.click(screen.getByRole("radio", { name: "미정으로 유지" }));
  view.rerender(<Conversation job={second} select={vi.fn()} onAction={vi.fn()} busy={false} />);
  expect(screen.getByRole("textbox", { name: "수정 의견 또는 추가 요청" })).toHaveValue("");
  expect(screen.getByRole("radio", { name: "미정으로 유지" })).not.toBeChecked();
  view.rerender(<Conversation job={{ ...first, read_only: true }} select={vi.fn()} onAction={vi.fn()} busy={false} />);
  expect(screen.getByRole("textbox", { name: "수정 의견 또는 추가 요청" })).toHaveValue("첫 작업");
  expect(screen.queryByRole("button", { name: "답변을 수정 의견에 추가" })).toBeNull();
});
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
