import { expect, it } from "vitest";
import { decodeJob } from "./job-response";

it("과거 작업의 선택 필드 누락을 허용한다", () => {
  expect(decodeJob({ id: "old", status: "blocked" })).toEqual({ id: "old", status: "blocked" });
});
it("완료 문서 ID 없이 단계만 가리키는 과거 참조를 허용한다", () => {
  expect(decodeJob({ id: "old", status: "FINALIZED", latest_completed: { step_id: "final" } }).latest_completed).toEqual({ step_id: "final" });
});
it("완료 여부가 없는 과거 작업 결과를 완료로 추정하지 않는다", () => {
  const result = decodeJob({ id: "old", status: "waiting", state: { task_results: [{ action: "interview", revision: 1 }] } });
  expect(result.state?.task_results?.[0].status).toBeUndefined();
});
it("잘못된 질문 선택지는 컴포넌트에 전달하지 않는다", () => {
  expect(() => decodeJob({ id: "j", status: "waiting", state: { question_forms: { q: { options: "broken" } } } })).toThrow();
});
it("이미 저장한 답변과 선택 정보는 유지한다", () => {
  const saved = { question_id: "q", answer: "선택", selection: { form_version: "1", selected_option_ids: ["a"] } };
  expect(decodeJob({ id: "j", status: "waiting", state: { saved_answers: [saved] } }).state?.saved_answers).toEqual([saved]);
});
