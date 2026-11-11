import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import Admin from "@/features/admin/Admin";
import { api } from "@/shared/api/api";

vi.mock("@/shared/api/api", () => ({ api: vi.fn(), post: vi.fn() }));
vi.mock("@/features/auth/Auth", () => ({ useAuth: () => ({ user: { id: "admin", role: "admin" } }) }));
vi.mock("@/features/knowledge/Knowledge", () => ({ default: () => null }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("임베딩 오류가 없는 null 응답으로 운영 현황을 표시한다", async () => {
  vi.mocked(api).mockResolvedValue({ embedding_status: null, executions: [] });
  render(<MemoryRouter initialEntries={["/admin"]}><Admin /></MemoryRouter>);
  expect(await screen.findByText("현재 실행 0개")).toBeTruthy();
  expect(screen.getByText("임베딩 오류 없음")).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toBe("");
});

it("문자열 임베딩 상태 메시지를 표시한다", async () => {
  vi.mocked(api).mockResolvedValue({ embedding_status: "임베딩 색인 확인 필요", executions: [] });
  render(<MemoryRouter initialEntries={["/admin"]}><Admin /></MemoryRouter>);
  expect(await screen.findByText("임베딩 색인 확인 필요")).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toBe("");
});

it.each([123, {}])("잘못된 임베딩 상태 %j를 거부하고 다시 조회로 복구한다", async (embedding_status) => {
  vi.mocked(api).mockResolvedValueOnce({ embedding_status })
    .mockResolvedValue({ embedding_status: null, executions: [] });
  render(<MemoryRouter initialEntries={["/admin"]}><Admin /></MemoryRouter>);
  await screen.findByText("문자열 응답이 필요합니다.");
  fireEvent.click(screen.getByRole("button", { name: "다시 조회" }));
  expect(await screen.findByText("현재 실행 0개")).toBeTruthy();
  expect(screen.getByText("임베딩 오류 없음")).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toBe("");
});

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
  await screen.findByRole("combobox", { name: "사용자" }, { timeout: 10000 });
  fireEvent.click(screen.getByRole("combobox", { name: "사용자" })); fireEvent.click(await screen.findByRole("option", { name: "one" }));
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
  fireEvent.click(screen.getByRole("combobox", { name: "사용자" })); fireEvent.click(await screen.findByRole("option", { name: "empty" }));
  await screen.findByText("조회된 작업이 없습니다");
  expect(vi.mocked(api).mock.calls.some(([path]) => path.includes("user_jobs"))).toBe(false);
}, 15000);
// 이 검사는 관리자 동작을 검증하므로 lazy 모듈 변환은 수집 단계에 끝낸다.
import '@/features/admin/JobData';
