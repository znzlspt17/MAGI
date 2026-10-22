import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QuestionActions } from "./QuestionActions";
import type { Job, QuestionForm } from "./types";
vi.mock("./Auth", () => ({ useAuth: () => ({ publicMode: false, user: null, status: {} }) }));
afterEach(cleanup);
beforeEach(() => sessionStorage.clear());
const form: QuestionForm = { question_id: "STORAGE", question: "기록을 어디에 저장할까요?", form_version: "v1", input_type: "single_choice", options: [
  { id: "local", label: "기기에 저장", impact: "로그인 없이 시작하기 쉽지만 다른 기기와 공유하려면 별도 방법이 필요합니다.", assumptions: ["한 기기 사용을 우선하는 경우"] },
  { id: "server", label: "서버에 저장", impact: "여러 기기에서 사용할 수 있지만 운영 비용을 검토해야 합니다.", assumptions: ["기기 간 기록을 이어 보려면 사용자 식별 방법이 필요합니다."] }],
  recommendation: { option_ids: ["local"], reason: "현재 요청은 한 기기에서 간편하게 사용하는 것을 우선합니다.", assumptions: ["기기 간 이어 보기가 필수가 아닌 경우"] } };
const job = (f = form): Job => ({ id: "job", status: "NEEDS_USER_INPUT", state: { blocking_questions: ["[STORAGE] 기록을 어디에 저장할까요?"], question_forms: { STORAGE: f } } });

it("영향과 추천 전제를 기본 표시하고 자동 선택·제출하지 않는다", async () => {
  const action = vi.fn(); render(<QuestionActions job={job()} onAction={action} busy={false} />);
  const local = screen.getByRole("radio", { name: "기기에 저장" }) as HTMLInputElement;
  expect(local.checked).toBe(false);
  expect(screen.getByText(form.options[0].impact!)).toBeTruthy();
  expect(screen.getByText("추천 전제: 기기 간 이어 보기가 필수가 아닌 경우")).toBeTruthy();
  expect(local.getAttribute("aria-describedby")).toBeTruthy();
  expect(screen.getByText("추천", { exact: true })).toBeTruthy();
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "답변 제출" })));
  expect(action).not.toHaveBeenCalled();
  expect(screen.getByRole("alert").textContent).toContain("하나 이상");
});

it("다른 선택을 명시적으로 제출하며 영향·추천·전제를 답변에 붙이지 않는다", async () => {
  const action = vi.fn().mockResolvedValue(undefined); render(<QuestionActions job={job()} onAction={action} busy={false} />);
  fireEvent.click(screen.getByRole("radio", { name: "서버에 저장" }));
  expect(screen.getByText("선택됨", { exact: true })).toBeTruthy();
  expect(action).not.toHaveBeenCalled();
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "답변 제출" })));
  expect(action).toHaveBeenCalledWith("answer", [{ question_id: "STORAGE", question: form.question, answer: "서버에 저장", selected_option_ids: ["server"], custom_text: null, form_version: "v1" }]);
});

it("복수 추천에서 일부만 선택하거나 직접 입력을 추가할 수 있다", async () => {
  const multiple = { ...form, input_type: "multiple_choice" as const, recommendation: { ...form.recommendation!, option_ids: ["local", "server"] } };
  const action = vi.fn().mockResolvedValue(undefined); render(<QuestionActions job={job(multiple)} onAction={action} busy={false} />);
  expect(screen.getAllByText("추천", { exact: true })).toHaveLength(2);
  expect(screen.getByText("기기에 저장 + 서버에 저장", { exact: true })).toBeTruthy();
  fireEvent.click(screen.getByRole("checkbox", { name: "기기에 저장" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "직접 입력" }));
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "내보내기로 공유" } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "답변 제출" })));
  expect(action.mock.calls[0][1][0].answer).toBe("기기에 저장\n내보내기로 공유");
});

it("추천 보류와 설명 없는 과거 폼을 구분하고 기존 초안을 복원한다", () => {
  const noRecommendation = { ...form, recommendation: null };
  const view = render(<QuestionActions job={job(noRecommendation)} onAction={vi.fn()} busy={false} />);
  expect(screen.getByText("현재 정보로는 추천을 정하기 어렵습니다")).toBeTruthy();
  fireEvent.click(screen.getByRole("radio", { name: "서버에 저장" }));
  const old = { ...form, options: form.options.map(({ id, label }) => ({ id, label })), recommendation: undefined };
  view.rerender(<QuestionActions job={job(old)} onAction={vi.fn()} busy={false} />);
  expect(screen.queryByText("현재 정보로는 추천을 정하기 어렵습니다")).toBeNull();
  expect((screen.getByRole("radio", { name: "서버에 저장" }) as HTMLInputElement).checked).toBe(true);
});

it("안내가 바뀐 새 버전은 이전 초안을 자동 채택하지 않는다", () => {
  const view = render(<QuestionActions job={job()} onAction={vi.fn()} busy={false} />);
  fireEvent.click(screen.getByRole("radio", { name: "기기에 저장" }));
  view.rerender(<QuestionActions job={job({ ...form, form_version: "v2" })} onAction={vi.fn()} busy={false} />);
  expect((screen.getByRole("radio", { name: "기기에 저장" }) as HTMLInputElement).checked).toBe(false);
});

it("검토 원문을 펼쳐도 HTML을 실행하지 않는다", () => {
  const value = job(); value.state!.review_questions = [{ question_id: "STORAGE", resolution_reasons: ["저장 방법을 결정해야 합니다."], evidence: [{ source: "draft", quote: "<img src=x onerror=alert(1)>" }] }];
  const view = render(<QuestionActions job={value} onAction={vi.fn()} busy={false} />);
  fireEvent.click(screen.getByRole("button", { name: "명세 검토 근거 보기" }));
  expect(screen.getByText(/<img src=x/)).toBeTruthy();
  expect(view.container.querySelector("img")).toBeNull();
});
