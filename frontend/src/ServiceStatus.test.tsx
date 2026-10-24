import { expect, it } from "vitest";
import { serviceState } from "./ServiceStatus";

it("다른 사용자의 실행과 대기열은 새 요청을 차단하지 않는다", () => {
  for (const active_count of [0,1,2]) {
    expect(serviceState(true, {ready:true,active_count,queued_count:3,max_parallel:2,own_active_count:0}).blocked).toBe(false);
  }
  expect(serviceState(true, {checkState:"error"}).blocked).toBe(true);
  expect(serviceState(true, {checkState:"loading"}).blocked).toBe(true);
});
