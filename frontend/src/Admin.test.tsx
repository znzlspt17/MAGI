import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import Admin from "./Admin";
import { api } from "./api";

vi.mock("./api", () => ({ api: vi.fn(), post: vi.fn() }));
vi.mock("./Auth", () => ({ useAuth: () => ({ user: { id: "admin", role: "admin" } }) }));
vi.mock("./Knowledge", () => ({ default: () => null }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("사용자별 작업 목록에서 상세를 열고 작업 ID로도 조회한다", async () => {
  vi.mocked(api).mockImplementation(async (path: string) => {
    if (path === "/api/admin/overview") return { users: [{ id: "one" }, { id: "empty" }] };
    if (path.includes("cleanup/catalog")) return { jobs: [], pending: [] };
    if (path.includes("owner_id=one")) return [{ id: "job-one", request: "사용자 작업", status: "FINALIZED" }];
    if (path.includes("owner_id=empty")) return [];
    return { id: "job-one", request: "사용자 작업", owner_id: "one", status: "FINALIZED" };
  });
  render(<MemoryRouter initialEntries={["/admin/data"]}><Admin /></MemoryRouter>);
  await screen.findByRole("option", { name: "one" });
  fireEvent.change(screen.getByLabelText("사용자별 작업 조회"), { target: { value: "one" } });
  const list = screen.getByLabelText("사용자 작업 목록");
  fireEvent.click(await within(list).findByRole("button", { name: "상세 조회" }));
  await screen.findByText("소유자: one");
  expect(screen.getByLabelText<HTMLInputElement>("작업 ID").value).toBe("job-one");
  fireEvent.click(screen.getByRole("button", { name: "조회" }));
  expect(api).toHaveBeenCalledWith("/api/admin/job?id=job-one");
  fireEvent.change(screen.getByLabelText("사용자별 작업 조회"), { target: { value: "empty" } });
  await screen.findByText("이 사용자의 작업이 없습니다.");
  expect(screen.queryByText("소유자: one")).toBeNull();
});
