import { expect, it } from "vitest";
import { serviceState } from "./ServiceStatus";

it("다른 사용자 점유·조회 실패·복구 중에는 전송을 차단한다", () => {
  for (const status of [{}, { checkState: "error" as const }, { busy: true, mine: false }, { busy: true, mine: true, recovering: true }]) {
    expect(serviceState(true, status).blocked).toBe(true);
  }
  expect(serviceState(true, { busy: true, mine: false }).title).toBe("다른 사용자가 이용 중입니다");
  expect(serviceState(true, { busy: true, mine: true, phase: "waiting" }).title).toBe("내 답변을 기다리고 있습니다");
  expect(serviceState(true, { busy: false, mine: false }).blocked).toBe(false);
});
