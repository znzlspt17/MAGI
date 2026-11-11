import { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import Workspace from "@/features/workspace/Workspace";

const scenario = vi.hoisted(() => ({ oldOnly: false }));

vi.mock("@/features/auth/Auth", () => ({ useAuth: () => ({ publicMode: false, user: null, status: {}, notice: "", setNotice: vi.fn() }) }));
vi.mock("@/features/projects/ProjectDecisions", () => ({ ProjectDecisionPicker: () => null, ReusedDecisions: () => null }));
vi.mock("@/features/knowledge/Knowledge", () => ({ default: () => null }));
vi.mock("@/features/workspace/ServiceStatus", () => ({ serviceState: () => ({ blocked: false }), ServiceStatusNotice: () => null }));
vi.mock("@/features/workspace/useJobSession", () => ({ useJobSession: () => {
  const [tab, setTab] = useState(scenario.oldOnly ? "document" : "conversation"), [step, select] = useState(scenario.oldOnly ? "old" : "candidate");
  const job = { id: "job", status: "PASS_PENDING_USER_APPROVAL", execution_id: "new", state: { status: "PASS_PENDING_USER_APPROVAL" },
    execution_graph: { nodes: scenario.oldOnly ? [{ id: "old", has_document: true, execution_id: "previous" }] : [{ id: "candidate", has_document: true, execution_id: "new" }] }, completed_documents: scenario.oldOnly ? [] : [{ id: "old", has_document: true }] };
  return { jobs: [], job, step, tab, setTab, select, detail: { document: { content: "명세 본문", language: "ko" }, result: {} }, busy: false, loading: false, connection: "", refresh: vi.fn(), command: vi.fn() };
} }));
vi.mock("@/features/conversation/Conversation", () => ({ Conversation: ({ select }: { select: (step: string) => void }) => {
  const [draft, setDraft] = useState("");
  return <section aria-label="대화 테스트"><label>수정 의견<input value={draft} onChange={event => setDraft(event.target.value)} /></label><button>이 명세 승인</button><button onClick={() => select("old")}>이전 문서 열기</button></section>;
} }));
vi.mock("@/features/documents/DocumentView", () => ({ DocumentView: () => <p>명세 본문</p> }));
vi.mock("@/features/documents/ImplementationPackage", () => ({ ImplementationPackage: () => null }));

beforeEach(() => {
  vi.stubGlobal("scrollTo", vi.fn());
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); scenario.oldOnly = false; });

it("대화와 명세 전환에서 동일한 수정 초안과 하나의 승인 동작을 유지한다", async () => {
  render(<MemoryRouter initialEntries={["/jobs/job"]}><Routes><Route path="/jobs/:id" element={<Workspace />} /></Routes></MemoryRouter>);
  fireEvent.change(screen.getByLabelText("수정 의견"), { target: { value: "보관 기간 수정" } });
  await userEvent.click(screen.getByRole("tab", { name: "명세" }));
  expect(screen.getByText("명세 본문")).toBeVisible();
  expect(screen.getByLabelText("수정 의견")).toHaveValue("보관 기간 수정");
  expect(screen.getAllByRole("button", { name: "이 명세 승인" })).toHaveLength(1);
  await userEvent.click(screen.getByRole("tab", { name: "대화" }));
  expect(screen.getByLabelText("수정 의견")).toHaveValue("보관 기간 수정");
});

it("이전 문서는 읽기 전용이며 현재 검토본으로 돌아가면 승인 동작을 복원한다", () => {
  render(<MemoryRouter initialEntries={["/jobs/job"]}><Routes><Route path="/jobs/:id" element={<Workspace />} /></Routes></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "이전 문서 열기" }));
  expect(screen.getByText("이전 시점의 명세")).toBeVisible();
  expect(screen.queryByRole("button", { name: "이 명세 승인" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "현재 검토본 열기" }));
  expect(screen.getAllByRole("button", { name: "이 명세 승인" })).toHaveLength(1);
});

it("작은 화면 검토 패널은 열 때 닫기 버튼에 초점을 주고 Escape 후 원위치한다", async () => {
  vi.stubGlobal("innerWidth", 1024);
  render(<MemoryRouter initialEntries={["/jobs/job"]}><Routes><Route path="/jobs/:id" element={<Workspace />} /></Routes></MemoryRouter>);
  await userEvent.click(screen.getByRole("tab", { name: "명세" }));
  const opener = screen.getByRole("button", { name: "대화와 검토 열기" });
  fireEvent.click(opener);
  const closer = within(screen.getByRole("complementary", { name: "대화와 검토 동작" })).getByRole("button", { name: "대화와 검토 닫기" });
  expect(closer).toHaveFocus();
  fireEvent.keyDown(closer, { key: "Escape" });
  expect(opener).toHaveFocus();
  expect(opener).toHaveAttribute("aria-expanded", "false");
});

it("현재 검토본이 확인되지 않는 이전 실행 문서 옆에는 승인 동작을 표시하지 않는다", () => {
  scenario.oldOnly = true;
  render(<MemoryRouter initialEntries={["/jobs/job"]}><Routes><Route path="/jobs/:id" element={<Workspace />} /></Routes></MemoryRouter>);
  expect(screen.queryByRole("button", { name: "이 명세 승인" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "대화에서 현재 상태 확인" })).toBeVisible();
});
