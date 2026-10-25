import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import Admin from "./Admin";
import { api } from "./api";

vi.mock("./api", () => ({ api: vi.fn(), post: vi.fn() }));
vi.mock("./Auth", () => ({ useAuth: () => ({ user: { id: "admin", role: "admin" } }) }));
vi.mock("./Knowledge", () => ({ default: () => null }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("사용자 목록의 빈 결과를 명시한다", async () => {
  vi.mocked(api).mockResolvedValue({ users: [] });
  render(<MemoryRouter initialEntries={["/admin/users"]}><Admin /></MemoryRouter>);
  expect(await screen.findByText("등록된 사용자가 없습니다.")).toBeTruthy();
});

it("사용자 조회 오류에서 다시 조회하면 빈 결과로 복구한다", async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error("조회 실패")).mockResolvedValue({ users: [] });
  render(<MemoryRouter initialEntries={["/admin/users"]}><Admin /></MemoryRouter>);
  await screen.findByText("조회 실패");
  fireEvent.click(screen.getByRole("button", { name: "다시 조회" }));
  expect(await screen.findByText("등록된 사용자가 없습니다.")).toBeTruthy();
  expect(screen.queryByText("조회 실패")).toBeNull();
});

it("통합 목록의 사용자 필터와 작업 ID 직접 조회를 연결한다", async () => {
  vi.mocked(api).mockImplementation(async (path: string) => {
    if (path === "/api/admin/overview") return { users: [{ id: "one" }, { id: "empty" }] };
    if (path.includes("cleanup/catalog")) return { jobs: [{ id: "job-one", request: "사용자 작업", owner_id: "one", status: "FINALIZED" }], pending: [] };
    return { id: "job-one", request: "사용자 작업", owner_id: "one", status: "FINALIZED" };
  });
  render(<MemoryRouter initialEntries={["/admin/data"]}><Admin /></MemoryRouter>);
  await screen.findByRole("option", { name: "one" }, { timeout: 10000 });
  fireEvent.change(screen.getByLabelText("사용자", { selector: "select" }), { target: { value: "one" } });
  const list = screen.getByRole("table");
  fireEvent.click(await within(list).findByRole("button", { name: "상세 조회" }));
  const panel = await screen.findByRole("dialog", { name: "작업 상세" });
  await within(panel).findByText("전체 요청 내용");
  expect(within(panel).getByText("one")).toBeTruthy();
  fireEvent.click(within(panel).getByRole("button", { name: "닫기" }));
  expect(screen.getByLabelText<HTMLInputElement>("작업 ID").value).toBe("job-one");
  fireEvent.click(screen.getByRole("button", { name: "조회" }));
  expect(api).toHaveBeenCalledWith("/api/admin/job?id=job-one");
  fireEvent.click(within(await screen.findByRole("dialog", { name: "작업 상세" })).getByRole("button", { name: "닫기" }));
  fireEvent.change(screen.getByLabelText("사용자", { selector: "select" }), { target: { value: "empty" } });
  await screen.findByText("조회된 작업이 없습니다");
  expect(vi.mocked(api).mock.calls.some(([path]) => path.includes("user_jobs"))).toBe(false);
}, 15000);
// 이 검사는 관리자 동작을 검증하므로 lazy 모듈 변환은 수집 단계에 끝낸다.
import './JobData';
