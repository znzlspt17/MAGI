import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ExecutionMonitor, elapsedLabel } from "@/features/execution/ExecutionMonitor";
import { applyProgress } from "@/features/workspace/progress-state";

afterEach(() => { cleanup(); vi.useRealTimers(); });
it("실행 중인 세부 상태만 회전하고 완료되면 멈춘다", () => {
  const job = { id: "j", status: "running", execution_id: "e", execution_graph: { nodes: [{ id: "s", execution_id: "e", stage: "planner", status: "running" }] } };
  const { container, rerender } = render(<ExecutionMonitor job={job} select={vi.fn()} />);
  fireEvent.click(screen.getByRole("button"));
  expect(container.querySelector('.execution-monitor-steps .status-icon.is-running')).not.toBeNull();
  rerender(<ExecutionMonitor job={{ ...job, status: "FINALIZED", execution_graph: { nodes: [{ ...job.execution_graph.nodes[0], status: "completed" }] } }} select={vi.fn()} />);
  expect(container.querySelector('.status-icon.is-running')).toBeNull();
});
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

it("전체 시간은 대기 시작부터 유지하고 단계 시간은 상태에 따라 표시한다", () => {
  vi.useFakeTimers(); vi.setSystemTime(new Date("2026-11-03T00:10:00Z"));
  const job = { id: "j", status: "running", execution_id: "e", queued_at: "2026-11-03T00:00:00Z", execution_graph: { nodes: [
    { id: "answer", execution_id: "e", stage: "answer", status: "completed", started_at: "2026-11-03T00:00:00Z" },
    { id: "done", execution_id: "e", stage: "spec_compile", status: "completed", started_at: "2026-11-03T00:01:00Z", completed_at: "2026-11-03T00:04:40Z" },
    { id: "missing", execution_id: "e", stage: "planner", status: "completed", started_at: "2026-11-03T00:05:00Z" },
    { id: "current", execution_id: "e", stage: "checklist_critic", status: "running", started_at: "2026-11-03T00:09:09Z" },
  ] } };
  const { unmount, rerender } = render(<ExecutionMonitor job={job} select={vi.fn()} />);
  expect(screen.getByLabelText("경과 시간 10분 0초")).toBeTruthy();
  fireEvent.click(screen.getByRole("button"));
  expect(within(screen.getByRole("button", { name: /답변 저장/ })).queryByText(/초/)).toBeNull();
  expect(within(screen.getByRole("button", { name: /명세 생성/ })).getByText("3분 40초")).toBeTruthy();
  expect(within(screen.getByRole("button", { name: /작업 계획/ })).getByText("소요 시간 기록 없음")).toBeTruthy();
  expect(within(within(screen.getByRole("list", { name: "현재 실행 단계" })).getByRole("button", { name: /명세 검토/ })).getByText("51초")).toBeTruthy();
  act(() => vi.advanceTimersByTime(1000));
  expect(screen.getByLabelText("경과 시간 10분 1초")).toBeTruthy();
  expect(within(screen.getByRole("button", { name: /명세 생성/ })).getByText("3분 40초")).toBeTruthy();
  expect(within(within(screen.getByRole("list", { name: "현재 실행 단계" })).getByRole("button", { name: /명세 검토/ })).getByText("52초")).toBeTruthy();
  rerender(<ExecutionMonitor job={{ ...job, execution_graph: { nodes: [...job.execution_graph.nodes.slice(0, 3), { ...job.execution_graph.nodes[3], stage: "planner" }] } }} select={vi.fn()} />);
  expect(screen.getByLabelText("경과 시간 10분 1초")).toBeTruthy();
  unmount();
  const snapshot = applyProgress(undefined, { event: "job.snapshot", job_id: "j", revision: 1, server_time: "2026-11-03T00:10:01Z", job }).state!;
  render(<ExecutionMonitor job={snapshot.job} select={vi.fn()} />);
  expect(screen.getByLabelText("경과 시간 10분 1초")).toBeTruthy();
});

it("유효한 현재 실행 시작을 복원하고 새 실행과 종료 시간을 구분한다", () => {
  vi.useFakeTimers(); vi.setSystemTime(new Date("2026-11-03T00:10:00Z"));
  const job = { id: "j", status: "running", execution_id: "e", queued_at: "invalid", execution_graph: { nodes: [
    { id: "old", execution_id: "old", started_at: "2026-11-03T00:00:00Z" },
    { id: "later", execution_id: "e", started_at: "2026-11-03T00:09:30Z", status: "running" },
    { id: "invalid", execution_id: "e", started_at: "invalid" },
    { id: "first", execution_id: "e", started_at: "2026-11-03T00:08:00Z", status: "completed" },
    { id: "failed", execution_id: "e", stage: "checklist_critic", started_at: "2026-11-03T00:08:30Z", status: "failed" },
  ] } };
  const { rerender } = render(<ExecutionMonitor job={job} select={vi.fn()} />);
  expect(screen.getByLabelText("경과 시간 2분 0초")).toBeTruthy();
  rerender(<ExecutionMonitor job={{ ...job, execution_id: "new", queued_at: "2026-11-03T00:09:50Z" }} select={vi.fn()} />);
  expect(screen.getByLabelText("경과 시간 10초")).toBeTruthy();
  rerender(<ExecutionMonitor job={{ ...job, status: "completed", queued_at: "2026-11-03T00:00:00Z", updated_at: "2026-11-03T00:09:45Z" }} select={vi.fn()} />);
  act(() => vi.advanceTimersByTime(2000));
  expect(screen.getByLabelText("경과 시간 9분 45초")).toBeTruthy();
  fireEvent.click(screen.getByRole("button"));
  expect(within(screen.getByRole("button", { name: /명세 검토/ })).getByText("소요 시간 기록 없음")).toBeTruthy();
  expect(within(screen.getByRole("list", { name: "현재 실행 단계" })).getByText("15초")).toBeTruthy();
  rerender(<ExecutionMonitor job={{ id: "j", status: "running", execution_id: "e" }} select={vi.fn()} />);
  expect(screen.getByLabelText("경과 시간 시작 시각 확인 중")).toBeTruthy();
});

it("서버 시각에 맞춰 전체 시간을 계산한다", () => {
  vi.useFakeTimers(); vi.setSystemTime(new Date("2026-11-03T01:00:00Z"));
  const job = { id: "j", status: "running", execution_id: "e", queued_at: "2026-11-03T00:00:00Z", server_time: "2026-11-03T00:02:00Z" };
  const { unmount } = render(<ExecutionMonitor job={job} select={vi.fn()} />);
  expect(screen.getByLabelText("경과 시간 2분 0초")).toBeTruthy();
  act(() => vi.advanceTimersByTime(1000));
  expect(screen.getByLabelText("경과 시간 2분 1초")).toBeTruthy();
  unmount();
  const reconnected = applyProgress(undefined, { event: "job.snapshot", job_id: "j", revision: 5, server_time: "2026-11-03T00:02:01Z", job }).state!;
  render(<ExecutionMonitor job={reconnected.job} select={vi.fn()} />);
  expect(screen.getByLabelText("경과 시간 2분 1초")).toBeTruthy();
});
