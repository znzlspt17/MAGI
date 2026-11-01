import { expect, it } from "vitest";
import { decodeStepDetail } from "./execution-detail";

it("과거 단계는 유지하고 누락된 선택 필드를 허용한다", () => {
  expect(decodeStepDetail({ id: "old", stage: "legacy" })).toMatchObject({ id: "old", stage: "legacy" });
});

it("잘못된 진단 목록을 화면으로 전달하지 않는다", () => {
  const detail = decodeStepDetail({ id: "stop", result: { stop_diagnostic: { issues: "invalid" } } });
  expect(detail.recording_incomplete).toBe(true);
  expect(detail.result?.stop_diagnostic).toBeUndefined();
});

it("형식이 잘못된 최상위 응답은 실패한다", () => {
  expect(() => decodeStepDetail(["invalid"])).toThrow();
});
it("문서 기록이 훼손되어도 남은 진단은 표시한다", () => {
  const detail = decodeStepDetail({ id: "stop", document: { content: [] }, result: { wait_reason: "보완 한도" } });
  expect(detail.recording_incomplete).toBe(true);
  expect(detail.document).toBeUndefined();
  expect(detail.result?.wait_reason).toBe("보완 한도");
});
