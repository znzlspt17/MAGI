import { useState } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import JobData from "./JobData";
import { api, post } from "./api";
import { filterJobs, jobTime } from "./job-data";

vi.mock("./api", () => ({ api: vi.fn(), post: vi.fn() }));
const entries = [
  { id: "recent", owner_id: "owner", request: "긴 요청 내용 ".repeat(30), status: "FINALIZED", created_at: "2026-10-21T01:00:00Z" },
  { id: "older", owner_id: "other", request: "오류가 발생한 작업", status: "error", created_at: "2026-10-20T01:00:00Z" },
  { id: "unowned", owner_id: null, request: "내부 작업", status: "NEEDS_USER_INPUT" },
];
function Harness() {
  const [version, setVersion] = useState(0);
  const location = useLocation();
  return <><output aria-label="현재 주소">{location.search}</output><JobData users={[{ id: "owner" }, { id: "other" }]} version={version} busy={false} refresh={() => setVersion(v => v + 1)} /></>;
}
function mount(url = "/admin/data") { return render(<MemoryRouter initialEntries={[url]}><Harness /></MemoryRouter>); }
beforeEach(() => {
  vi.mocked(api).mockImplementation(async (path: string) => path.includes("catalog") ? { jobs: entries, pending: ["pending"] } : { ...entries[0], final: "# 최종 문서", session_events: [] });
  vi.mocked(post).mockResolvedValue({ id: "preview", scope: "jobs", targets: ["recent"], counts: { jobs: 1 } });
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) { this.setAttribute("open", ""); });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("시각이 없는 작업은 뒤로 정렬하고 한국 시간과 복합 필터를 적용한다", () => {
  expect(filterJobs(entries, "", "", "").map(row => row.id)).toEqual(["recent", "older", "unowned"]);
  expect(filterJobs(entries, "오류", "other", "error").map(row => row.id)).toEqual(["older"]);
  expect(filterJobs(entries, "unowned", "unowned", "NEEDS_USER_INPUT")).toHaveLength(1);
  expect(jobTime("2026-10-20T15:00:00Z")).toContain("26. 10. 21.");
  expect(jobTime("bad")).toBe("기록 없음");
});
it("제목·상태·사용자·작업 ID를 별도 셀로 표시하고 필터 변경 시 선택을 해제한다", async () => {
  mount(); const table = await screen.findByRole("table");
  expect(within(table).getAllByRole("columnheader").map(cell => cell.textContent)).toEqual(["선택", "작업 제목", "상태", "사용자", "작업 ID", "생성 시각 (KST)", "상세 조회"]);
  expect(within(table).getByText("최종 완료")).toBeTruthy();
  fireEvent.click(within(table).getByRole("checkbox", { name: "작업 recent 선택" }));
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "선택 작업 삭제 미리보기" }).disabled).toBe(false);
  fireEvent.change(screen.getByLabelText("작업 검색"), { target: { value: "other" } });
  expect(within(table).getAllByRole("checkbox")).toHaveLength(1);
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "선택 작업 삭제 미리보기" }).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("사용자", { selector: "select" }), { target: { value: "unowned" } });
  await screen.findByText("조회된 작업이 없습니다");
});
it("25개 단위로 페이지를 나누고 페이지 이동·새로고침 시 선택을 해제한다", async () => {
  vi.mocked(api).mockResolvedValue({ jobs: Array.from({ length: 27 }, (_, i) => ({ ...entries[0], id: "job-" + String(i).padStart(2, "0") })), pending: [] });
  mount(); const table = await screen.findByRole("table");
  expect(within(table).getAllByRole("checkbox")).toHaveLength(25);
  fireEvent.click(screen.getByLabelText("현재 페이지 전체 선택"));
  expect(screen.getByText("검색 결과 27개 · 선택 25개")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "다음" }));
  expect(within(table).getAllByRole("checkbox")).toHaveLength(2);
  expect(screen.getByText("검색 결과 27개 · 선택 0개")).toBeTruthy();
  fireEvent.click(screen.getByLabelText("현재 페이지 전체 선택"));
  fireEvent.click(screen.getByRole("button", { name: "목록 새로고침" }));
  await waitFor(() => expect(screen.getByText("검색 결과 27개 · 선택 0개")).toBeTruthy());
});
it("직접 링크의 상세·빈 탭·닫기 동작과 다른 쿼리 매개변수를 유지한다", async () => {
  mount("/admin/data?job_id=recent&keep=1");
  const panel = await screen.findByRole("dialog", { name: "작업 상세" });
  await within(panel).findByText("전체 요청 내용");
  fireEvent.mouseDown(within(panel).getByRole("tab", { name: "처리 이력" }), { button: 0, ctrlKey: false });
  await within(panel).findByText("저장된 처리 이력이 없습니다.");
  fireEvent.click(within(panel).getByRole("button", { name: "닫기" }));
  expect(screen.getByLabelText("현재 주소").textContent).toBe("?keep=1");
});
it("패널을 닫은 뒤 도착한 응답을 무시하고 조회 오류에서 재시도한다", async () => {
  let resolve!: (value: unknown) => void;
  vi.mocked(api).mockImplementation(async (path: string) => path.includes("catalog") ? { jobs: entries, pending: [] } : new Promise(done => { resolve = done; }));
  mount("/admin/data?job_id=recent");
  const panel = await screen.findByRole("dialog", { name: "작업 상세" });
  await within(panel).findByText("작업을 조회하는 중…");
  fireEvent.click(within(panel).getByRole("button", { name: "닫기" }));
  await act(async () => resolve({ ...entries[0], request: "늦은 응답" }));
  expect(screen.queryByText("늦은 응답")).toBeNull();
  vi.mocked(api).mockRejectedValueOnce(new Error("조회 실패"));
  fireEvent.change(screen.getByLabelText("작업 ID"), { target: { value: "retry" } });
  fireEvent.click(screen.getByRole("button", { name: "조회" }));
  await screen.findByText("조회 실패");
  vi.mocked(api).mockResolvedValue(entries[1]);
  fireEvent.click(screen.getByRole("button", { name: "다시 조회" }));
  await screen.findByText("전체 요청 내용");
});
it("선택한 작업만 미리보고 전체 삭제의 확인 문구와 복구 재시도를 유지한다", async () => {
  mount(); const table = await screen.findByRole("table");
  fireEvent.click(within(table).getByLabelText("작업 recent 선택"));
  fireEvent.click(screen.getByRole("button", { name: "선택 작업 삭제 미리보기" }));
  await screen.findByRole("dialog", { name: "영구 삭제 확인" });
  expect(post).toHaveBeenCalledWith("/api/admin/cleanup/preview", { scope: "jobs", ids: ["recent"] });
  fireEvent.click(screen.getByRole("button", { name: "취소" }));
  vi.mocked(post).mockResolvedValueOnce({ id: "all-preview", scope: "all", counts: { jobs: 3 } });
  fireEvent.click(screen.getByText("위험 작업 · 전체 기록 삭제"));
  fireEvent.click(screen.getByRole("button", { name: "전체 기록 삭제 미리보기" }));
  const confirm = await screen.findByRole("dialog", { name: "영구 삭제 확인" });
  expect(within(confirm).getByRole<HTMLButtonElement>("button", { name: "영구 삭제" }).disabled).toBe(true);
  fireEvent.change(within(confirm).getByLabelText("계속하려면 “전체 기록 삭제”를 입력하세요."), { target: { value: "전체 기록 삭제" } });
  expect(within(confirm).getByRole<HTMLButtonElement>("button", { name: "영구 삭제" }).disabled).toBe(false);
  vi.mocked(post).mockResolvedValueOnce({ state: "completed" });
  fireEvent.click(within(confirm).getByRole("button", { name: "영구 삭제" }));
  await waitFor(() => expect(post).toHaveBeenCalledWith("/api/admin/cleanup/execute", { id: "all-preview", confirmation: "전체 기록 삭제" }));
  fireEvent.click(await screen.findByRole("button", { name: "남은 파일 정리 재시도 · pending" }));
  await waitFor(() => expect(post).toHaveBeenCalledWith("/api/admin/cleanup/execute", { id: "pending", confirmation: "" }));
});
