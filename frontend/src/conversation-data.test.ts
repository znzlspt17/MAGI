import { describe, expect, it } from "vitest";
import { conversationTurns } from "./conversation-data";
import type { Job } from "./types";

const job = (session_events: Job["session_events"]): Job => ({ id: "job", status: "running", request: "요청", session_events });
describe("공개 대화 projection", () => {
  it("답변과 질문 참조를 원문 순서로 분리하고 빈 답변은 제외한다", () => {
    const answers = [{ question_id: "Q1", question: "첫 질문", answer: "첫 답변\n다음 줄" }, { question_id: "Q2", answer: "질문 없는 답변" }, { question: "빈 답변", answer: "  " }];
    const value = job([{ id: "e", action: "answer", input: { answers } }]);
    const before = JSON.stringify(value);
    const { turns } = conversationTurns(value);
    expect(turns).toHaveLength(1);
    expect(turns[0].text).toBe("");
    expect(turns[0].answers).toEqual(answers.slice(0, 2));
    expect(JSON.stringify(value)).toBe(before);
  });
  it("직접 입력과 승인 메시지는 기존 표시를 유지한다", () => {
    const { turns } = conversationTurns(job([{ id: "f", action: "revise", input: { feedback: "추가 요청" } }, { id: "a", action: "approve" }]));
    expect(turns.map(turn => turn.text)).toEqual(["추가 요청", "이 명세를 승인했습니다."]);
    expect(turns.every(turn => !turn.answers)).toBe(true);
  });
  it("사용자 입력과 실제 MAGI 요약을 분리하고 과거 문서 링크를 보존한다", () => {
    const { turns } = conversationTurns(job([{ id: "e", action: "generate", input: { request: "실제 요청" }, summary: "실제 요약", document_step_id: "old-doc", questions: ["[Q1] 질문"] }]));
    expect(turns.map((turn) => [turn.id, turn.role, turn.text])).toEqual([["e:user", "user", "실제 요청"], ["e:magi", "magi", "실제 요약"]]);
    expect(turns[1].documentStepId).toBe("old-doc");
  });
  it("반복된 실행 ID는 한 번만 표시하고 최신 요약으로 갱신한다", () => {
    const { turns } = conversationTurns(job([{ id: "e", action: "answer", input: { answers: [{ question: "질문", answer: "부분 답변" }] }, summary: "이전" }, { id: "e", action: "answer", input: { answers: [{ question: "질문", answer: "부분 답변" }] }, summary: "최신" }]));
    expect(turns).toHaveLength(2);
    expect(turns[1].text).toBe("최신");
  });
  it("실행 상태만으로 AI 답변·사고·도구 호출을 꾸며내지 않는다", () => {
    expect(conversationTurns(job([{ id: "e", action: "generate", status: "running", input: { request: "실제 입력" } }])).turns).toEqual([expect.objectContaining({ role: "user", text: "실제 입력" })]);
  });
  it("이력 누락 시 원래 요청만 복원하고 누락을 알린다", () => {
    const value = conversationTurns(job([]));
    expect(value.incomplete).toBe(true);
    expect(value.turns).toHaveLength(1);
    expect(value.turns[0].text).toBe("요청");
  });
});
