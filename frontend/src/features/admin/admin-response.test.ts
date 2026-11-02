import { expect, it } from "vitest";
import { decodeAdminJob, decodeCleanup, decodeLogPage, decodeUsageRows } from "./admin-response";

it("문서·시각이 없는 이력의 null과 과거 필드 누락을 구분한다", () => {
  const events = [{ id: "e", action: "generate", started_at: null, document_step_id: null }, { id: "old", action: "generate" }];
  expect(decodeAdminJob({ id: "j", session_events: events }).session_events).toEqual(events);
});
it.each([123, {}])("이력 참조·시각과 사용량 요청의 잘못된 타입 %j를 거부한다", value => {
  for (const key of ["started_at", "document_step_id"]) {
    expect(() => decodeAdminJob({ id: "j", session_events: [{ [key]: value }] })).toThrow();
  }
  expect(() => decodeUsageRows({ rows: [{ user_id: "u", request: value }], total: 1 })).toThrow();
});
it("사용량 요청의 명시적 null은 보존하고 누락은 추가하지 않는다", () => {
  expect(decodeUsageRows({ rows: [{ user_id: "u", request: null }, { user_id: "u" }], total: 2 }).rows)
    .toEqual([{ user_id: "u", request: null }, { user_id: "u" }]);
  expect(() => decodeAdminJob({ session_events: [] })).toThrow();
});

it("삭제 미리보기의 개수가 잘못되면 실행 화면에 전달하지 않는다", () => {
  expect(() => decodeCleanup({ id: "preview", scope: "jobs", counts: { jobs: "2" } })).toThrow();
});
it("로그 필드의 중첩 객체를 문자열로 추정하지 않는다", () => {
  expect(() => decodeLogPage({ items: [{ fields: { unexpected: {} } }] })).toThrow();
});
it("정산 금액의 소수 문자열과 사용량 미확정을 보존한다", () => {
  const result = decodeUsageRows({ rows: [{ user_id: "u", actual: "0.00000001", input_tokens: null }], total: 1, limit: 25, offset: 0 });
  expect(result.rows[0].actual).toBe("0.00000001");
  expect(result.rows[0].input_tokens).toBeNull();
});
