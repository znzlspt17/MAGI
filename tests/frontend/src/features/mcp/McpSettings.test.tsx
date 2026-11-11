import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { McpSettings } from "@/features/mcp/McpSettings";
import { api, sensitiveMutation } from "@/shared/api/api";

vi.mock("@/shared/api/api", () => ({ api: vi.fn(), sensitiveMutation: vi.fn() }));
vi.mock("@/features/auth/Auth", () => ({ useAuth: () => ({ user: { id: "owner" } }) }));
afterEach(() => { cleanup(); vi.clearAllMocks(); window.history.replaceState({}, "", "/"); });
const connection = { id: "one", name: "문서 서버", url: "https://example.test/mcp", auth_type: "api_key", enabled: false,
  status: "ready", has_credential: true, error: null, api_key_header: "X-API-Key",
  tools: [{ name: "search", description: "문서 검색", read_only_hint: true, destructive_hint: false, enabled: true, schema_changed: false, available: true, disabled_reason: null },
    { name: "write", description: "쓰기", read_only_hint: false, destructive_hint: true, enabled: false, schema_changed: false, available: false, disabled_reason: "읽기 전용 아님" }] };

it("연결 활성 여부와 연결 상태를 각각 확인할 수 있다", async () => {
  vi.mocked(api).mockResolvedValue({ connections: [connection] });
  render(<McpSettings />);
  await screen.findByText("문서 서버");
  expect(screen.getByText("비활성")).toBeTruthy();
  expect(screen.getByText("연결됨")).toBeTruthy();
});

it("등록된 조회 도구만 선택할 수 있고 활성 연결 적용 범위를 표시한다", async () => {
  vi.mocked(api).mockResolvedValue({ connections: [connection] });
  render(<McpSettings />);
  await screen.findByText("문서 서버");
  expect(screen.getByText(/새 작업에 자동 적용/)).toBeTruthy();
  expect((screen.getByRole("checkbox", { name: /search/ }) as HTMLInputElement).checked).toBe(true);
  expect((screen.getByRole("checkbox", { name: /write/ }) as HTMLInputElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("checkbox", { name: /search/ }));
  fireEvent.click(screen.getByRole("button", { name: "도구 선택 저장" }));
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(([path, options]) =>
    path === "/api/mcp/connections/one" && options?.body === JSON.stringify({ selected_tools: [] }))).toBe(true));
});

it("저장된 인증값은 표시하지 않고 새 값은 민감 요청으로 전송한다", async () => {
  vi.mocked(api).mockResolvedValue({ connections: [connection] });
  vi.mocked(sensitiveMutation).mockResolvedValue(connection);
  render(<McpSettings />);
  await screen.findByText("문서 서버");
  fireEvent.click(screen.getByRole("button", { name: "수정" }));
  const field = screen.getByLabelText<HTMLInputElement>("API 키");
  expect(field.value).toBe("");
  fireEvent.change(field, { target: { value: "fake-secret" } });
  fireEvent.click(within(screen.getByRole("heading", { name: "연결 수정" }).parentElement!).getByRole("button", { name: "저장" }));
  await waitFor(() => expect(sensitiveMutation).toHaveBeenCalledWith("/api/mcp/connections/one", "PATCH",
    expect.objectContaining({ credential: "fake-secret" }), expect.any(String)));
  expect(screen.queryByDisplayValue("fake-secret")).toBeNull();
});

it("인증 만료와 도구 스키마 변경을 안내한다", async () => {
  vi.mocked(api).mockResolvedValue({ connections: [{ ...connection, auth_type: "oauth", status: "auth_required",
    tools: [{ ...connection.tools[0], enabled: false, schema_changed: true }] }] });
  render(<McpSettings />);
  expect(await screen.findByText(/변경됨, 다시 선택 필요/)).toBeTruthy();
  expect(screen.getByText(/인증 필요/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "다시 인증" })).toBeTruthy();
});

it("목록 오류를 표시한다", async () => {
  vi.mocked(api).mockRejectedValue(new Error("목록 조회 실패"));
  render(<McpSettings />);
  expect((await screen.findByRole("alert")).textContent).toContain("목록 조회 실패");
});

it("서버가 비활성으로 판정한 조회 도구는 선택을 막고 이유를 보여준다", async () => {
  vi.mocked(api).mockResolvedValue({ connections: [{ ...connection, tools: [
    { ...connection.tools[0], enabled: false, available: false, disabled_reason: "지원하지 않는 스키마" },
  ] }] });
  render(<McpSettings />);
  expect(await screen.findByText(/지원하지 않는 스키마/)).toBeTruthy();
  expect((screen.getByRole("checkbox", { name: /search/ }) as HTMLInputElement).disabled).toBe(true);
});

it("OAuth 실패 플래그를 안전한 안내로 표시하고 원문을 표시하지 않는다", async () => {
  window.history.replaceState({}, "", "/settings/mcp?oauth=failed&error=UNTRUSTED_ERROR");
  vi.mocked(api).mockResolvedValue({ connections: [] });
  render(<McpSettings />);
  expect(await screen.findByText("인증 연결에 실패했습니다. 다시 시도해 주세요.")).toBeTruthy();
  expect(screen.queryByText(/UNTRUSTED_ERROR/)).toBeNull();
});

it("사용자 지정 API 키 헤더는 수정 화면과 저장 요청에서 유지된다", async () => {
  vi.mocked(api).mockResolvedValue({ connections: [{ ...connection, api_key_header: "X-Custom-Auth" }] });
  vi.mocked(sensitiveMutation).mockResolvedValue({ ...connection, api_key_header: "X-Custom-Auth" });
  render(<McpSettings />);
  await screen.findByText("문서 서버");
  fireEvent.click(screen.getByRole("button", { name: "수정" }));
  expect(screen.getByLabelText<HTMLInputElement>("API 키 헤더 이름").value).toBe("X-Custom-Auth");
  fireEvent.click(within(screen.getByRole("heading", { name: "연결 수정" }).parentElement!).getByRole("button", { name: "저장" }));
  await waitFor(() => expect(sensitiveMutation).toHaveBeenCalledWith("/api/mcp/connections/one", "PATCH",
    expect.objectContaining({ api_key_header: "X-Custom-Auth" }), expect.any(String)));
});

it("기존 OAuth 클라이언트 ID를 지우면 null로 전달하고 비밀번호는 유지한다", async () => {
  const oauth = { ...connection, auth_type: "oauth", oauth_client_id: "old-client", status: "auth_required" };
  vi.mocked(api).mockResolvedValue({ connections: [oauth] });
  vi.mocked(sensitiveMutation).mockResolvedValue({ ...oauth, oauth_client_id: null });
  render(<McpSettings />);
  await screen.findByText("문서 서버");
  fireEvent.click(screen.getByRole("button", { name: "수정" }));
  fireEvent.change(screen.getByLabelText<HTMLInputElement>("OAuth 클라이언트 ID (선택)"), { target: { value: "" } });
  fireEvent.click(within(screen.getByRole("heading", { name: "연결 수정" }).parentElement!).getByRole("button", { name: "저장" }));
  await waitFor(() => expect(sensitiveMutation).toHaveBeenCalledWith("/api/mcp/connections/one", "PATCH",
    expect.objectContaining({ oauth_client_id: null }), expect.any(String)));
  const payload = vi.mocked(sensitiveMutation).mock.calls[0][2] as Record<string, unknown>;
  expect(payload).not.toHaveProperty("oauth_client_secret");
});
