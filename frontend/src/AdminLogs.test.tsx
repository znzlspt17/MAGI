import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api } from "./api";
import AdminLogs from "./AdminLogs";
vi.mock("./api", () => ({ api: vi.fn() }));
const row = { timestamp: "2026-10-27T00:00:00Z", service: "backend", level: "info", message: "hello <script>literal</script>", event: "hello", fields: {} };
beforeEach(() => { vi.mocked(api).mockImplementation(async path => path.includes("/status") ? { state: "ready", retention_days: 7, collector_seen: true, free_bytes: 1024, warnings: [] } : { items: [row], start: "2026-10-26T23:45:00Z", end: row.timestamp, next_offset: 200, storage: { state: "ready" } }); });
afterEach(() => { cleanup(); vi.clearAllMocks(); window.history.replaceState(null, "", "/"); });
it("로그를 텍스트로 표시하고 과거 페이지의 기준 시각을 고정한다", async () => {
  render(<AdminLogs />);
  await screen.findByText(row.message);
  expect(screen.getByText("2026. 10. 27. 오전 9:00:00 KST")).toBeTruthy();
  expect(document.querySelector("script")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "이전 로그 더 보기" }));
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(([path]) => path.includes("offset=200") && path.includes("end=2026-10-27T00%3A00%3A00Z"))).toBe(true));
  expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(false);
});
it("검색 조건만 전송하고 상세 열기와 스크롤에서 갱신을 멈춘다", async () => {
  render(<AdminLogs />); await screen.findByText(row.message);
  fireEvent.change(screen.getByLabelText("메시지 검색"), { target: { value: "실패" } });
  fireEvent.click(screen.getByRole("button", { name: "검색" }));
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(([path]) => path.includes("q=%EC%8B%A4%ED%8C%A8") && !path.includes("period="))).toBe(true));
  fireEvent.wheel(document.querySelector(".logs-list")!);
  expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(false);
});
it("저장소 장애를 빈 결과와 구분하고 자동 재시도 폭주를 막는다", async () => {
  vi.mocked(api).mockRejectedValue(new Error("로그 저장소에 연결할 수 없습니다."));
  render(<AdminLogs />);
  await waitFor(() => expect(screen.getAllByText("로그 저장소에 연결할 수 없습니다.").length).toBeGreaterThan(0));
  expect(screen.queryByText("조건에 맞는 로그가 없습니다.")).toBeNull();
  expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(false);
});

it("진단에서 전달한 작업·실행 필터를 화면과 첫 조회에 적용한다", async () => {
  window.history.replaceState(null, "", "/admin/logs?job_id=job&execution_id=run&period=10080&query=ignored");
  render(<AdminLogs />); await screen.findByText(row.message);
  expect((screen.getByLabelText("작업 ID") as HTMLInputElement).value).toBe("job");
  expect((screen.getByLabelText("실행 ID") as HTMLInputElement).value).toBe("run");
  expect((screen.getByLabelText("기간") as HTMLSelectElement).value).toBe("10080");
  const path = vi.mocked(api).mock.calls.find(([path]) => path.startsWith("/api/admin/logs?"))![0];
  expect(path).toContain("job_id=job"); expect(path).toContain("execution_id=run");
  expect(path).not.toContain("query="); expect(path).not.toContain("period=");
});
