import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { api } from "./api";
import { RequirementReview, type RequirementReviewData } from "./RequirementReview";
vi.mock("./api", () => ({ api: vi.fn() }));
afterEach(cleanup);
beforeEach(() => vi.mocked(api).mockReset());
const evidence = { item_id: "A", section: "architecture", quote: "Check owner before reading.", start: 0, end: 27, line: 3, shared: true, provenance: "recorded_block" };
const report: RequirementReviewData = { status: "ready", message: "연결이 구현의 동작을 보증하지 않습니다.", basis: { id: "basis", source_hash: "source" }, review_status: "pending_approval",
  summary: { total: 25, spec_linked: 1, acceptance_linked: 0, verification_linked: 0 }, rows: [{ id: "REQ-001", text: "사용자별 기록 격리", group: "mandatory_requirements", spec_status: "linked", acceptance_status: "unconfirmed", verification_status: "unconfirmed", test_status: "not_collected", specification: [evidence], acceptance: [], verification: [], specification_total: 1, acceptance_total: 0, verification_total: 0 }],
  unlinked: [], unlinked_total: 1, total: 25, has_more: true, offset: 0 };

it("문서 상태와 실제 테스트를 분리하고 인용·수정 의견·전체 근거를 연결한다", async () => {
  vi.mocked(api).mockImplementation(async path => String(path).includes("evidence_for=") ? { ...report, rows: [], evidence: [evidence], total: 1, has_more: false } : report as any);
  const locate = vi.fn(), question = vi.fn();
  render(<RequirementReview jobId="job" stepId="step" sourceHash="source" onLocate={locate} onQuestion={question} />);
  await screen.findByText("사용자별 기록 격리");
  expect(screen.getByText("명세 근거 연결 1/25")).toBeTruthy();
  expect(screen.getByText("명세 문서 검토 통과 · 사용자 승인 대기")).toBeTruthy();
  expect(screen.getByText("결과 미수집", { exact: true })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "수정 의견에 추가" }));
  expect(question).toHaveBeenCalledWith(expect.stringContaining("REQ-001"));
  fireEvent.click(screen.getByRole("button", { name: "architecture · 3행" }));
  fireEvent.click(screen.getByRole("button", { name: "명세 원문 위치로 이동" }));
  expect(locate).toHaveBeenCalledWith(evidence);
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  fireEvent.click(screen.getByRole("button", { name: "REQ-001 연결 근거 전체 보기" }));
  await waitFor(() => expect(api).toHaveBeenCalledWith(expect.stringContaining("evidence_for=REQ-001"), expect.anything()));
  expect((await screen.findAllByText("공통 근거", { exact: true })).length).toBeGreaterThan(0);
  expect(vi.mocked(api).mock.calls.every(([, options]) => !options?.method || options.method === "GET")).toBe(true);
});

it("요약은 모델 호출 없이 전체 근거 보기로 이어진다", async () => {
  vi.mocked(api).mockResolvedValue(report);
  const open = vi.fn();
  render(<RequirementReview jobId="job" compact onOpen={open} />);
  await screen.findByText("실제 테스트 결과 미수집");
  expect(screen.queryByRole("table")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "전체 근거 보기" }));
  expect(open).toHaveBeenCalledOnce();
});

it("페이지·필터·검색을 서버에 전달하고 요약은 전체 수치를 유지한다", async () => {
  vi.mocked(api).mockResolvedValue(report);
  render(<RequirementReview jobId="job" />);
  await screen.findByText("사용자별 기록 격리");
  const pagination = screen.getByRole("navigation", { name: "요구사항 근거 페이지" });
  fireEvent.click(within(pagination).getByRole("button", { name: "다음" }));
  await waitFor(() => expect(api).toHaveBeenLastCalledWith(expect.stringContaining("offset=20"), expect.anything()));
  await screen.findByText("사용자별 기록 격리");
  fireEvent.change(screen.getByRole("combobox", { name: "요구사항 연결 필터" }), { target: { value: "missing" } });
  await waitFor(() => expect(api).toHaveBeenLastCalledWith(expect.stringContaining("missing=true"), expect.anything()));
  await screen.findByText("사용자별 기록 격리");
  fireEvent.change(screen.getByRole("textbox", { name: "요구사항 검색" }), { target: { value: "REQ-001" } });
  await waitFor(() => expect(api).toHaveBeenLastCalledWith(expect.stringContaining("query=REQ-001"), expect.anything()));
});

it("이전 작업의 늦은 응답이 새 선택을 덮지 않는다", async () => {
  let resolve!: (value: any) => void;
  vi.mocked(api).mockReturnValueOnce(new Promise(done => { resolve = done; })).mockResolvedValue({ ...report, rows: [] });
  const view = render(<RequirementReview jobId="old" />);
  view.rerender(<RequirementReview jobId="new" />);
  await screen.findByText("표시할 요구사항이 없습니다");
  await act(async () => resolve(report));
  expect(screen.queryByText("사용자별 기록 격리")).toBeNull();
});

it("자료 부족·기준 불일치·조회 실패·재시도를 구분한다", async () => {
  vi.mocked(api).mockResolvedValueOnce({ ...report, status: "limited" }).mockResolvedValueOnce(report).mockRejectedValueOnce(new Error("조회 실패"));
  const view = render(<RequirementReview jobId="old" />);
  await screen.findByText(/요구사항별 연결 자료 부족/);
  view.rerender(<RequirementReview jobId="new" sourceHash="different" />);
  await screen.findByText(/기준 문서가 다릅니다/);
  fireEvent.click(screen.getByRole("button", { name: "근거표 다시 조회" }));
  await screen.findByText("조회 실패");
});

it("기준 명세가 준비되기 전에는 결과를 만들지 않는다", async () => {
  vi.mocked(api).mockResolvedValue({ status: "unavailable", message: "기준 명세가 없습니다." });
  render(<RequirementReview jobId="job" />);
  await screen.findByText("검토 근거 준비 전");
  expect(screen.queryByText("결과 미수집", { exact: true })).toBeNull();
});

it("부모 화면이 갱신돼도 펼친 근거와 인용을 유지한다", async () => {
  vi.mocked(api).mockImplementation(async path => String(path).includes("evidence_for=") ? { ...report, evidence: [evidence], total: 1, has_more: false } : report as any);
  const view = render(<RequirementReview jobId="job" onLocate={() => {}} />);
  await screen.findByText("사용자별 기록 격리");
  fireEvent.click(screen.getByRole("button", { name: "REQ-001 연결 근거 전체 보기" }));
  await waitFor(() => expect(document.querySelector(".rr-evidence")).toBeTruthy());
  fireEvent.click(within(document.querySelector(".rr-evidence") as HTMLElement).getByRole("button", { name: "architecture · 3행" }));
  await screen.findByRole("dialog");
  const calls = vi.mocked(api).mock.calls.length;
  view.rerender(<RequirementReview jobId="job" onLocate={() => {}} />);
  expect(screen.getByRole("dialog")).toBeTruthy();
  expect(vi.mocked(api).mock.calls.length).toBe(calls);
});
