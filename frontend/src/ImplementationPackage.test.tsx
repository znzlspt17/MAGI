import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api, apiBlob } from "./api";
import { ImplementationPackage, type PackageMetadata } from "./ImplementationPackage";
vi.mock("./api", () => ({ api: vi.fn(), apiBlob: vi.fn() }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
beforeEach(() => { vi.mocked(api).mockReset(); vi.mocked(apiBlob).mockReset(); });
const metadata: PackageMetadata = { completed_id: "a".repeat(64), bundle_id: "b".repeat(64), filename: "approved.zip", available: true, completeness: "complete", korean_included: false, task_count: 3, total_size: 1200, source_hash: "c".repeat(64), files: [{ name: "SPEC.en.md", size: 1000, sha256: "d".repeat(64) }], limitations: ["저장된 번역 없음 · 영어 원문 포함"] };
const open = () => fireEvent.click(screen.getByRole("button", { name: "구현 묶음 다운로드" }));

it("버전과 파일 목록을 미리 보고 고정한 승인본으로 ZIP을 받는다", async () => {
  vi.mocked(api).mockResolvedValue(metadata);
  vi.mocked(apiBlob).mockResolvedValue(new Blob(["zip"]));
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn(() => "blob:package") });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  const links: HTMLAnchorElement[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function(this: HTMLAnchorElement) { links.push(this); });
  render(<ImplementationPackage jobId="job" completedId={metadata.completed_id} />);
  expect(api).not.toHaveBeenCalled(); open();
  await screen.findByText("SPEC.en.md");
  expect(screen.getByRole("dialog", { name: "구현 시작용 파일 묶음" })).toBeTruthy();
  expect(screen.getByText("구조화 작업 3개")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "버전 전체 값과 해시" }));
  expect(screen.getByText(metadata.completed_id)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "ZIP 받기" }));
  await screen.findByText("브라우저에 ZIP 다운로드를 전달했습니다.");
  expect(apiBlob).toHaveBeenCalledWith(expect.stringContaining(`completed_id=${metadata.completed_id}&bundle_id=${metadata.bundle_id}`), expect.anything());
  expect(links[0].download).toBe("approved.zip");
});

it("중복 클릭을 막고 닫은 뒤의 늦은 다운로드는 전달하지 않는다", async () => {
  vi.mocked(api).mockResolvedValue(metadata);
  let resolve!: (blob: Blob) => void;
  vi.mocked(apiBlob).mockReturnValue(new Promise(done => { resolve = done; }));
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: vi.fn() });
  render(<ImplementationPackage jobId="job" />); open(); await screen.findByText("SPEC.en.md");
  fireEvent.click(screen.getByRole("button", { name: "ZIP 받기" }));
  fireEvent.click(screen.getByRole("button", { name: "ZIP 받기" }));
  expect(apiBlob).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "닫기" }));
  await act(async () => resolve(new Blob(["zip"])));
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it("자료 부족·크기 초과·조회 실패와 재조회를 구분한다", async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error("조회 실패")).mockResolvedValue({ ...metadata, completeness: "limited", available: false, limitations: ["크기 제한 초과"] });
  render(<ImplementationPackage jobId="job" />); open();
  await screen.findByText("조회 실패");
  fireEvent.click(screen.getByRole("button", { name: "포함 자료 다시 조회" }));
  await screen.findByText("작업 연결 자료 부족");
  expect((screen.getByRole("button", { name: "ZIP 받기" }) as HTMLButtonElement).disabled).toBe(true);
});

it("작업 전환 뒤 이전 미리보기 응답을 버린다", async () => {
  let resolve!: (value: any) => void;
  vi.mocked(api).mockReturnValueOnce(new Promise(done => { resolve = done; })).mockResolvedValue({ ...metadata, files: [] });
  const view = render(<ImplementationPackage jobId="old" />); open();
  view.rerender(<ImplementationPackage jobId="new" />);
  await act(async () => resolve(metadata));
  expect(screen.queryByRole("dialog")).toBeNull();
  open(); await waitFor(() => expect(api).toHaveBeenCalledWith(expect.stringContaining("/new/"), expect.anything()));
  expect(screen.queryByText("SPEC.en.md")).toBeNull();
});

it("승인본 없음과 한국어 번역 포함을 구분한다", async () => {
  vi.mocked(api).mockRejectedValueOnce({ status: 404 }).mockResolvedValue({ ...metadata, korean_included: true, limitations: [] });
  render(<ImplementationPackage jobId="job" />); open();
  await screen.findByText("승인된 명세가 없습니다");
  fireEvent.click(screen.getByRole("button", { name: "포함 자료 다시 조회" }));
  await screen.findByText("저장된 한국어 번역 포함");
});
