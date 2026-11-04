import { expect, it } from "vitest";
import { requirementGroups, stepContent } from "@/features/execution/step-view";

it("과거 요구사항 표현을 표시용 문자열 목록으로 변환한다", () => {
  expect(requirementGroups({ requirements: ["첫째", { id: "R1", text: "둘째" }] })).toEqual([
    { title: "확정 요구사항", items: ["첫째", "R1 둘째"] },
  ]);
});
it("알 수 없는 단계는 명시적인 과거 단계로 구분한다", () => {
  expect(stepContent({ id: "old", stage: "legacy_stage" }, { result: {} }).kind).toBe("legacy");
});
