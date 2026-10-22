import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { ImpactReview, type ImpactPage, type ImpactReport } from "./ImpactReview";

const mocks = vi.hoisted(() => ({ api: vi.fn(), post: vi.fn() }));
vi.mock("./api", () => mocks);
vi.mock("./Auth", () => ({ useAuth: () => ({ user: { id: "owner" }, status: { busy: false } }) }));
afterEach(cleanup);

const basis = { id: "basis", job_id: "job", source_hash: "hash", node_id: "req", status: "PASS_PENDING_USER_APPROVAL" };
const req = { id: "req", kind: "requirement", body: "Store notes.", section: "", requirement_id: "REQ-001" };
const spec = { id: "spec", kind: "spec", body: "Store notes locally.", section: "Storage", requirement_id: "" };
const page: ImpactPage = { basis, node: req, recorded: [{ target: spec, paths: [{ kind: "direct", nodes: [req, spec] }] }],
  total: 1, offset: 0, has_more: false, next_offset: 20, message: "기록된 연결도 영향 확정을 뜻하지 않습니다." };
const report: ImpactReport = { id: "report", status: "complete", stale: false, basis, proposal: "오프라인 지원", change_kind: "modify",
  coverage: { total: 5, included: 3, omitted: 2, truncated: 1, recorded_total: 1, recorded_included: 1 },
  inferred: [{ topic: "오프라인 저장", effect: "로컬 저장을 검토해야 합니다.", rationale: "네트워크 없이 사용할 수 있어야 합니다.", question: "동기화가 필요한가요?", evidence: [{ node_id: "spec", quote: "Store notes locally." }] }],
  limitations: ["제공된 문맥 안의 검토 제안입니다."], sources: [{ node_id: "spec", kind: "spec", text: "Store notes locally.", section: "Storage" }] };

function Location() { return <p data-testid="location">{useLocation().pathname}</p>; }
function wrap(nodeId = "req") {
  return <MemoryRouter><Routes><Route path="*" element={<><ImpactReview jobId="job" nodeId={nodeId} inspect={vi.fn()} /><Location /></>} /></Routes></MemoryRouter>;
}
beforeEach(() => { sessionStorage.clear(); mocks.api.mockReset().mockResolvedValue(page); mocks.post.mockReset().mockResolvedValue(report); });

describe("변경 영향 검토", () => {
  it("조회만으로 모델을 호출하지 않고 기록된 경로와 추정을 분리한다", async () => {
    render(wrap());
    await screen.findByText("기록된 연결 조회 완료");
    expect(mocks.post).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "변경 가정" }).getAttribute("maxlength")).toBe("4000");
    fireEvent.click(screen.getByRole("button", { name: "관계 경로 확인" }));
    expect(screen.getByText("직접 연결")).toBeTruthy();
    expect(screen.getByRole("button", { name: "1. REQ-001" })).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "변경 가정" }), { target: { value: "오프라인 지원" } });
    fireEvent.click(screen.getByRole("button", { name: "추가 영향 분석" }));
    await screen.findByText("오프라인 저장");
    expect(mocks.post).toHaveBeenCalledWith("/api/knowledge/impact", expect.objectContaining({ node_id: "req", basis_id: "basis", proposal: "오프라인 지원" }));
    expect(screen.getByText("모델 추정")).toBeTruthy();
    expect(screen.getByText(/2개 제외/)).toBeTruthy();
  });

  it("인용을 클릭으로 열고 확인 질문을 기존 수정 의견에 추가한다", async () => {
    sessionStorage.setItem("draft:owner:job:feedback", "기존 의견");
    render(wrap());
    await screen.findByText("기록된 연결 조회 완료");
    fireEvent.change(screen.getByRole("textbox", { name: "변경 가정" }), { target: { value: "오프라인 지원" } });
    fireEvent.click(screen.getByRole("button", { name: "추가 영향 분석" }));
    await screen.findByText("오프라인 저장");
    fireEvent.click(screen.getByRole("button", { name: "Storage" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Store notes locally.")).toBeTruthy();
    fireEvent.keyDown(dialog, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "수정 의견에 추가" }));
    expect(sessionStorage.getItem("draft:owner:job:feedback")).toContain("기존 의견\n\n변경 가정: 오프라인 지원");
    expect(sessionStorage.getItem("draft:owner:job:feedback")).toContain("동기화가 필요한가요?");
    expect(screen.getByTestId("location").textContent).toBe("/jobs/job");
  });

  it("연결이 없는 신규 요구사항도 추가 분석할 수 있다", async () => {
    mocks.api.mockResolvedValue({ ...page, node: null, recorded: [], total: 0 });
    render(wrap(""));
    await screen.findByText("기록된 연결 조회 완료");
    expect(screen.getByText("기록된 연결을 찾지 못했습니다", { exact: true })).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "변경 가정" }), { target: { value: "오프라인 지원" } });
    fireEvent.click(screen.getByRole("button", { name: "추가 영향 분석" }));
    await screen.findByText("오프라인 저장");
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ change_kind: "add", node_id: null });
  });

  it("실패와 이전 기준 상태를 표시하고 오래된 질문 전송을 막는다", async () => {
    mocks.post.mockResolvedValue({ ...report, stale: true });
    render(wrap());
    await screen.findByText("기록된 연결 조회 완료");
    fireEvent.change(screen.getByRole("textbox", { name: "변경 가정" }), { target: { value: "가정" } });
    fireEvent.click(screen.getByRole("button", { name: "추가 영향 분석" }));
    await screen.findByText("이전 기준의 분석 결과입니다");
    expect((screen.getByRole("button", { name: "수정 의견에 추가" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "기준 다시 조회" }));
    await waitFor(() => expect(mocks.api).toHaveBeenCalledTimes(2));
  });

  it("페이지 이동과 입력 검증은 추가 모델 호출을 만들지 않는다", async () => {
    mocks.api.mockResolvedValue({ ...page, total: 45, has_more: true });
    render(wrap());
    await screen.findByText("기록된 연결 조회 완료");
    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await waitFor(() => expect(mocks.api.mock.calls[1][0]).toContain("offset=20"));
    await screen.findByText("기록된 연결 조회 완료");
    fireEvent.click(screen.getByRole("button", { name: "추가 영향 분석" }));
    expect(await screen.findByText("변경 가정을 1~4000자로 입력하세요.")).toBeTruthy();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("노드 전환 뒤 도착한 이전 응답을 버린다", async () => {
    let resolve!: (value: ImpactPage) => void;
    mocks.api.mockImplementationOnce(() => new Promise<ImpactPage>(done => { resolve = done; })).mockResolvedValue({ ...page, recorded: [], total: 0 });
    const view = render(wrap());
    view.rerender(wrap("new-req"));
    await screen.findByText("기록된 연결 조회 완료");
    await act(async () => resolve(page));
    expect(screen.queryByRole("button", { name: "관계 경로 확인" })).toBeNull();
  });
});
