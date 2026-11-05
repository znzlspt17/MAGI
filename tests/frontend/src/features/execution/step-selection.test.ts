import { expect, it } from "vitest";
import { automaticStep } from "@/features/execution/step-selection";

it("보완 중단 시 이전 문서보다 마지막 중단 진단을 먼저 선택한다", () => {
  expect(automaticStep([
    { id: "draft", has_document: true },
    { id: "stop", stage: "workflow", status: "blocked" },
  ], "CRITICAL_BLOCKED")).toBe("stop");
});
it("완료된 작업은 기존 문서 선택을 유지한다", () => {
  expect(automaticStep([{ id: "doc", has_document: true }, { id: "done", status: "completed" }], "FINALIZED")).toBe("doc");
});
it("오류가 나면 이전 초안보다 현재 실패 단계를 기본으로 선택한다", () => {
  expect(automaticStep([{ id: "draft", has_document: true },
    { id: "failed", stage: "workflow", status: "failed" }], "error")).toBe("failed");
});
