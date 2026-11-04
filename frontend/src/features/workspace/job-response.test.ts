import { expect, it } from "vitest";
import { decodeJob } from "./job-response";

it("과거 작업의 선택 필드 누락을 허용한다", () => {
  expect(decodeJob({ id: "old", status: "blocked" })).toEqual({ id: "old", status: "blocked" });
});
it("재시도 호출 유형을 확인하고 지원하지 않는 값은 거부한다", () => {
  expect(decodeJob({id:"j",status:"error",retry_kind:"mcp"}).retry_kind).toBe("mcp");
  expect(decodeJob({id:"j",status:"error",retry_kind:"none"}).retry_kind).toBe("none");
  expect(()=>decodeJob({id:"j",status:"error",retry_kind:"unknown"})).toThrow();
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

it("새 루브릭 평가의 누락·잘못된 판정을 거부하고 모델 원문을 제외한다", () => {
 const review = { score: 8, score_reason: "보완 필요", round: 3, selected_round: 1, selected_cycle: 1,
  termination: "patience", requires_acceptance: true, evaluation_hash: "e", revision_directives: [], remaining_issues: [], items: [], raw: "MODEL_RAW" };
 const result=decodeJob({id:"j",status:"waiting",state:{rubric_review:review}});
 expect(result.state?.rubric_review?.score).toBe(8);
 expect(JSON.stringify(result)).not.toContain("MODEL_RAW");
 expect(()=>decodeJob({id:"j",status:"waiting",state:{rubric_review:{...review,score:"8"}}})).toThrow();
 expect(()=>decodeJob({id:"j",status:"waiting",state:{rubric_review:{...review,termination:"unknown"}}})).toThrow();
 expect(()=>decodeJob({id:"j",status:"waiting",state:{rubric_review:{score:8}}})).toThrow();
});
