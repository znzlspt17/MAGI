import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import UsageDashboard from "./UsageDashboard";
import { api } from "./api";
import { money, presetRange } from "./usage-data";
vi.mock("./api", () => ({ api: vi.fn() }));
vi.mock("recharts", () => ({ ResponsiveContainer: ({ children }: any) => <div>{children}</div>, BarChart: () => <div />, Bar: () => null, CartesianGrid: () => null, Legend: () => null, Tooltip: () => null, XAxis: () => null, YAxis: () => null }));
const stats = { records: 30, calls: 29, pending_calls: 1, unknown_calls: 0, spent: "0.00000001", outstanding: "0.3", input_tokens: 100, output_tokens: 20, cached_tokens: null, input_recorded: 1, output_recorded: 1, cached_recorded: 0, missing_tokens: 28, missing_time: 2, uncertain: 1 };
const summary = { start: "2026-10-15", end: "2026-10-21", summary: stats, daily: [], today: { day: "2026-10-21", spent: "0.1", outstanding: "0.3", limit: "10" }, users: [{ id: "owner" }] };
const row = { ...stats, user_id: "owner", job_id: "job-id", request: "조회할 작업" };
const save = vi.fn().mockResolvedValue({ ok: true });
beforeEach(() => {
  vi.mocked(api).mockImplementation(async (path: string) => path.includes("/rows?") ? { rows: [path.includes("group_by=call") ? { ...row, id: "call-id", model: "gpt-6-luna", state: "settled" } : row], total: 30 } : summary);
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });
function mount() { return render(<MemoryRouter><UsageDashboard version={0} save={save} /></MemoryRouter>); }

it("호출별 표에서 사용량 기반 산정·수동 정산·불완전한 근거를 구분한다", async () => {
  const evidence = ["unknown", "complete", "manual", "missing_usage"];
  vi.mocked(api).mockImplementation(async (path: string) => path.includes("/rows?") ? {
    rows: evidence.map((value, i) => ({ ...row, id: "call-" + i, state: value === "missing_usage" ? "uncertain" : "settled",
      settlement_source: value === "manual" ? "manual" : value === "missing_usage" ? null : "calculated", cost_evidence: value })), total: 4,
  } : summary);
  mount();
  await screen.findAllByRole("link", { name: "조회할 작업" });
  fireEvent.mouseDown(screen.getByRole("tab", { name: "호출별" }), { button: 0, ctrlKey: false });
  for (const label of ["정산 근거 기록 없음", "사용량 기반 산정", "수동 정산", "정산 근거 불완전"])
    expect(await screen.findByText(label, { selector: "small" })).toBeTruthy();
});

it("금액 정밀도와 한국 시간 기간 프리셋을 유지한다", () => {
  expect(money("0.00000001")).toBe("$0.00000001");
  expect(money("1234567.2")).toBe("$1,234,567.20000000");
  expect(presetRange("7", "2026-01-03")).toEqual({ start: "2025-12-28", end: "2026-01-03" });
  expect(presetRange("month", "2026-10-21").start).toBe("2026-10-01");
});
it("작업 상세 링크, 호출 드릴다운, 사용자 필터와 서버 페이지를 연결한다", async () => {
  mount();
  expect((await screen.findByRole("link", { name: "조회할 작업" })).getAttribute("href")).toBe("/admin/data?job_id=job-id");
  fireEvent.click(screen.getByRole("button", { name: "다음" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith(expect.stringContaining("offset=25")));
  fireEvent.change(screen.getByLabelText("사용자 필터"), { target: { value: "owner" } });
  await waitFor(() => expect(api).toHaveBeenCalledWith(expect.stringMatching(/user_id=owner.*offset=0/)));
  fireEvent.click(await screen.findByRole("button", { name: "호출 보기" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith(expect.stringMatching(/job_id=job-id.*group_by=call/)));
  expect(screen.getByRole("tab", { name: "호출별" }).getAttribute("aria-selected")).toBe("true");
});
it("유효하지 않은 기간은 요청하지 않고 빈 내역과 누락 토큰을 구분한다", async () => {
  vi.mocked(api).mockImplementation(async (path: string) => path.includes("/rows?") ? { rows: [], total: 0 } : summary);
  mount(); await screen.findByText("조회된 내역이 없습니다");
  expect(screen.getByText("토큰 기록 누락")).toBeTruthy();
  const before = vi.mocked(api).mock.calls.length;
  fireEvent.change(screen.getByLabelText("시작일"), { target: { value: "2099-01-01" } });
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(vi.mocked(api).mock.calls.length).toBe(before);
});
it("이전 조회 응답은 새 필터 결과를 덮어쓰지 않는다", async () => {
  let resolveOld!: (value: any) => void;
  let initial = true;
  vi.mocked(api).mockImplementation(async (path: string) => {
    if (path.includes("/rows?")) return { rows: [], total: 0 };
    if (initial) { initial = false; return new Promise(resolve => { resolveOld = resolve; }); }
    return summary;
  });
  mount();
  fireEvent.change(screen.getByLabelText("조회 기간"), { target: { value: "today" } });
  await screen.findByText("정산 완료된 내부 산정액");
  await act(async () => resolveOld({ ...summary, summary: { ...stats, spent: "99" } }));
  expect(screen.queryByText("$99.00000000")).toBeNull();
});
it("오류 후 재시도로 복구하고 수동 정산을 관리 영역에 전달한다", async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error("집계 실패"));
  mount(); await screen.findByText("집계 실패");
  fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
  await screen.findByText("정산 완료된 내부 산정액");
  vi.mocked(api).mockImplementation(async (path: string) => path.includes("/rows?") ? { rows: [{ ...row, id: "call-id", reserved: "0.3", state: "uncertain", usage_day: "2026-10-21", is_call: true }], total: 1 } : summary);
  fireEvent.mouseDown(screen.getByRole("tab", { name: "호출별" }), { button: 0, ctrlKey: false });
  fireEvent.click(await screen.findByRole("button", { name: "수동 정산" }));
  fireEvent.change(screen.getByLabelText("확인된 실제 비용 US$"), { target: { value: "0.01" } });
  fireEvent.click(screen.getByRole("button", { name: "정산 저장" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith("/api/admin/settle", { id: "call-id", actual: "0.01" }));
});
