import { expect, it } from "vitest";
import { decodeCleanup, decodeLogPage, decodeUsageRows } from "./admin-response";

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
