import { expect, it } from "vitest";
import { applyProgress, type ProgressEvent } from "@/features/workspace/progress-state";

const event = (revision: number, kind: ProgressEvent["event"] = "job.progress"): ProgressEvent => ({ event: kind, revision, job_id: "j", server_time: "2026-11-03T00:00:00Z", job: { id: "j", status: "running" } });
it("초기 snapshot·중복·누락을 구분한다", () => {
  const first = applyProgress(undefined, event(2, "job.snapshot")).state!;
  expect(applyProgress(first, event(2)).state).toBe(first);
  expect(applyProgress(first, event(4)).resync).toBe(true);
  expect(applyProgress(first, event(3)).state?.revision).toBe(3);
  expect(applyProgress(first, event(8, "job.snapshot")).state?.revision).toBe(8);
});
it("snapshot 전 이벤트는 적용하지 않는다", () => {
  expect(applyProgress(undefined, event(1))).toEqual({ state: undefined, resync: true });
});
