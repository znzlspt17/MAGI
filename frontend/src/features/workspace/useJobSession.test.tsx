import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { useJobSession } from "./useJobSession";

const mocks = vi.hoisted(() => ({ api: vi.fn(), post: vi.fn(), notice: vi.fn(), refreshStatus: vi.fn(async () => {}) }));
vi.mock("../../shared/api/api", () => ({ api: mocks.api, post: mocks.post }));
vi.mock("../auth/Auth", () => ({ useAuth: () => ({ user: { id: "user" }, notice: "", setNotice: mocks.notice, refreshStatus: mocks.refreshStatus }) }));
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
