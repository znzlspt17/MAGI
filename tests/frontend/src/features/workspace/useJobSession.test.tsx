import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { useJobSession } from "@/features/workspace/useJobSession";

const mocks = vi.hoisted(() => ({ api: vi.fn(), post: vi.fn(), notice: vi.fn(), refreshStatus: vi.fn(async () => {}) }));
vi.mock("@/shared/api/api", () => ({ api: mocks.api, post: mocks.post }));
vi.mock("@/features/auth/Auth", () => ({ useAuth: () => ({ user: { id: "user" }, notice: "", setNotice: mocks.notice, refreshStatus: mocks.refreshStatus }) }));
const id = "a".repeat(32);
class Socket {
  static OPEN = 1;
  static instances: Socket[] = [];
  readyState = 1;
  sent: unknown[] = [];
  onopen?: () => void;
  onmessage?: (event: { data: string }) => void;
  onclose?: () => void;
  constructor() { Socket.instances.push(this); }
  send(value: string) { this.sent.push(JSON.parse(value)); }
  close() { this.readyState = 3; }
  event(value: unknown) { this.onmessage?.({ data: JSON.stringify(value) }); }
}
function View() { const session = useJobSession(); return <><p>{session.job?.status || "loading"}</p><aside>{session.jobs.map(job => <span key={job.id}>{job.id}:{job.status}</span>)}</aside></>; }
function SelectionView() {
  const session = useJobSession();
  return <><p>선택 단계: {session.step}</p><p>현재 실패 코드: {session.failureDetail?.result?.diagnostic?.error_code || "없음"}</p>
    <button onClick={() => session.select("doc")}>이전 문서 선택</button><button onClick={session.refresh}>새로고침</button></>;
}
function TabView() {
  const session = useJobSession();
  return <><p>현재 탭: {session.tab}</p><p>선택 문서: {session.step}</p><button onClick={() => session.setTab("conversation")}>대화로 이동</button></>;
}
beforeEach(() => {
  vi.useFakeTimers(); Socket.instances = []; vi.stubGlobal("WebSocket", Socket);
  mocks.api.mockReset().mockImplementation(async (path: string) => path === "/api/jobs" ? [] : { id, status: "queued" });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });
it("push로 상태를 갱신하고 15초가 지나도 HTTP 상태 요청을 보내지 않는다", async () => {
  render(<MemoryRouter initialEntries={[`/jobs/${id}`]}><Routes><Route path="/jobs/:id" element={<View/>}/></Routes></MemoryRouter>);
  await act(async () => {});
  const socket = Socket.instances.at(-1)!;
  await act(async () => { socket.onopen?.(); });
  expect(socket.sent).toContainEqual({ event: "job.subscribe", job_id: id });
  const calls = mocks.api.mock.calls.length;
  await act(async () => { socket.event({ event: "job.snapshot", job_id: id, revision: 1, server_time: new Date().toISOString(), job: { id, status: "running" } }); });
  expect(screen.getByText("running")).toBeTruthy();
  await act(async () => { vi.advanceTimersByTime(16000); });
  expect(mocks.api).toHaveBeenCalledTimes(calls);
  await act(async () => { socket.event({ event: "job.progress", job_id: id, revision: 3, server_time: new Date().toISOString(), job: { id, status: "completed" } }); });
  expect(screen.getByText("running")).toBeTruthy();
  expect(socket.sent).toContainEqual({ event: "job.resync", job_id: id });
  expect(mocks.api).toHaveBeenCalledTimes(calls);
  await act(async () => {
    socket.event({ event: "jobs.snapshot", revisions: { [id]: 5 }, jobs: [{ id, status: "completed" }] });
    socket.event({ event: "jobs.changed", revision: 3, job_id: id, job: { id, status: "queued" } });
  });
  expect(screen.getByText(`${id}:completed`)).toBeTruthy();
  expect(mocks.api).toHaveBeenCalledTimes(calls);
});

it("수동으로 과거 문서를 선택하고 갱신해도 현재 실행의 실패 상세는 따로 유지한다", async () => {
  const job = { id, status: "error", execution_id: "current", state: { status: "ANALYZING" }, execution_graph: { nodes: [
    { id: "doc", has_document: true, status: "completed", detail_available: true, execution_id: "previous" },
    { id: "old-failure", status: "failed", detail_available: true, execution_id: "previous" },
    { id: "failure", status: "failed", detail_available: true, execution_id: "current" },
  ] } };
  mocks.api.mockImplementation(async (path: string) => path === "/api/jobs" ? [job] : path.endsWith("/steps/failure")
    ? { result: { diagnostic: { error_code: "CURRENT_FAILURE" } } } : path.includes("/steps/") ? { result: {} } : job);
  render(<MemoryRouter initialEntries={[`/jobs/${id}`]}><Routes><Route path="/jobs/:id" element={<SelectionView/>}/></Routes></MemoryRouter>);
  await act(async () => {});
  expect(screen.getByText("선택 단계: failure")).toBeTruthy();
  expect(screen.getByText("현재 실패 코드: CURRENT_FAILURE")).toBeTruthy();
  await act(async () => { fireEvent.click(screen.getByText("이전 문서 선택")); });
  expect(screen.getByText("선택 단계: doc")).toBeTruthy();
  await act(async () => { fireEvent.click(screen.getByText("새로고침")); });
  expect(screen.getByText("선택 단계: doc")).toBeTruthy();
  expect(screen.getByText("현재 실패 코드: CURRENT_FAILURE")).toBeTruthy();
  expect(mocks.api.mock.calls.some(([path]) => String(path).endsWith("/steps/old-failure"))).toBe(false);
});

it("승인 후보로 처음 진입하면 현재 명세를 열고 이후 사용자가 선택한 탭을 유지한다", async () => {
  const job = { id, status: "PASS_PENDING_USER_APPROVAL", execution_id: "new", state: { status: "PASS_PENDING_USER_APPROVAL" }, execution_graph: { nodes: [
    { id: "candidate", has_document: true, detail_available: true, execution_id: "new" },
  ] }, completed_documents: [{ id: "old", has_document: true }] };
  mocks.api.mockImplementation(async (path: string) => path === "/api/jobs" ? [job] : path.includes("/steps/") ? { result: {} } : job);
  render(<MemoryRouter initialEntries={[`/jobs/${id}`]}><Routes><Route path="/jobs/:id" element={<TabView/>}/></Routes></MemoryRouter>);
  await act(async () => {});
  expect(screen.getByText("현재 탭: document")).toBeTruthy();
  expect(screen.getByText("선택 문서: candidate")).toBeTruthy();
  await act(async () => { fireEvent.click(screen.getByText("대화로 이동")); });
  await act(async () => { Socket.instances.at(-1)!.event({ event: "job.snapshot", job_id: id, revision: 1, server_time: new Date().toISOString(), job }); });
  expect(screen.getByText("현재 탭: conversation")).toBeTruthy();
});
