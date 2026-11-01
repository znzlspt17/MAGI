import { expect, it } from "vitest";
import { decodeEvent } from "./event-response";

it("삭제 이벤트의 잘못된 식별자 목록을 거부한다", () => {
  expect(() => decodeEvent({ event: "records.deleted", ids: "all" })).toThrow();
});
it("모르는 이벤트는 상태 변경 대상으로 해석하지 않는다", () => {
  expect(decodeEvent({ event: "future.event" })).toEqual({ event: "unknown" });
});
