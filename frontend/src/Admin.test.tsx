import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import Admin from "./Admin";
import { api } from "./api";

vi.mock("./api", () => ({ api: vi.fn(), post: vi.fn() }));
vi.mock("./Auth", () => ({ useAuth: () => ({ user: { id: "admin", role: "admin" } }) }));
vi.mock("./Knowledge", () => ({ default: () => null }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("통합 목록의 사용자 필터와 작업 ID 직접 조회를 연결한다", async () => {
  vi.mocked(api).mockImplementation(async (path: string) => {
    if (path === "/api/admin/overview") return { users: [{ id: "one" }, { id: "empty" }], unowned: [] };
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
