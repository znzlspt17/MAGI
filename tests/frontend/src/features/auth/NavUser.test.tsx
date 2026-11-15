import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NavUser } from "@/features/auth/NavUser";
import { SidebarProvider } from "@/shared/ui/sidebar";

const rememberLink = vi.fn();
vi.mock("@/features/auth/Auth", () => ({ useAuth: () => ({
  user: { id: "guest", role: "user", identity_kind: "guest" },
  loginAvailable: true, rememberLink, setNotice: vi.fn(),
}) }));

beforeEach(() => { window.matchMedia = vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }); });
afterEach(() => { cleanup(); vi.clearAllMocks(); });
it("익명 사용자는 작업 화면에서 계정 연결을 시작할 수 있다", () => {
  render(<SidebarProvider><NavUser /></SidebarProvider>);
  const link = screen.getByRole("link", { name: "로그인해서 기록 이어가기" });
  expect(link.getAttribute("href")).toBe("/auth/google/start");
  link.addEventListener("click", event => event.preventDefault());
  fireEvent.click(link, { button: 0 });
  expect(rememberLink).toHaveBeenCalledOnce();
});
