import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ExecutionMonitor, elapsedLabel } from "./ExecutionMonitor";

afterEach(() => { cleanup(); vi.useRealTimers(); });
it("누락·음수 시각과 분 단위 시간을 처리한다", () => {
  expect(elapsedLabel()).toBe("시작 시각 확인 중");
  expect(elapsedLabel("2026-11-03T00:00:00Z", undefined, Date.parse("2026-11-02T00:00:00Z"))).toBe("0초");
  expect(elapsedLabel("2026-11-03T00:00:00Z", "2026-11-03T00:01:05Z")).toBe("1분 5초");
});
it("실제 활성 단계와 경과 시간을 표시하고 상세를 선택한다", () => {
  vi.useFakeTimers(); vi.setSystemTime(new Date("2026-11-03T00:00:23Z"));
  const select = vi.fn();
  render(<ExecutionMonitor job={{ id: "j", status: "running", execution_id: "e", execution_graph: { nodes: [
    { id: "old", execution_id: "old", title: "이전 실행", status: "running" },
    { id: "s", execution_id: "e", stage: "spec_compile", status: "running", started_at: "2026-11-03T00:00:00Z" }
  ] } }} select={select} />);
  expect(screen.getByText("명세 생성 중")).toBeTruthy();
  expect(screen.getByText("23초")).toBeTruthy();
  fireEvent.click(screen.getByRole("button"));
  expect(screen.queryByText("이전 실행")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /명세 생성.*실행 중/ }));
  expect(select).toHaveBeenCalledWith("s");
});
