import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { useState } from "react";
import { api, post } from "./api";
import { ApprovedDecisions, ProjectDecisionPicker, ReusedDecisions, type DecisionSelection } from "./ProjectDecisions";
vi.mock("./api", () => ({ api: vi.fn(), post: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
const item = { id: "registered", version: 1, active: true, decision_id: "DEC-DB", text: "Use PostgreSQL.", conditions: "A server is operated.", actor: "llm", project_id: "project", job_id: "job", completed_id: "c".repeat(64), source_hash: "h".repeat(64), source_available: true, evidence: [{ item_id: "DB", section: "architecture", quote: "Use PostgreSQL to store notes." }] };
const packet = { rows: [item], total: 1, next_offset: null, project_id: "project" };
function Harness() { const [project, setProject] = useState(""), [selections, setSelections] = useState<DecisionSelection[]>([]); return <MemoryRouter><ProjectDecisionPicker projectId={project} onProject={setProject} selections={selections} onSelections={setSelections} /><output data-testid="selection">{JSON.stringify(selections)}</output></MemoryRouter>; }

it("등록된 결정을 기본 선택하지 않고 ID·버전·해시만 선택한다", async () => {
  vi.mocked(api).mockImplementation(async path => path === "/api/projects" ? [{ id: "project", name: "기록 서비스" }] : packet);
  render(<Harness />);
  await screen.findByRole("option", { name: "기록 서비스" });
  fireEvent.change(screen.getByLabelText("프로젝트"), { target: { value: "project" } });
  fireEvent.click(screen.getByRole("button", { name: "공통 결정 선택 · 0개" }));
  const checkbox = await screen.findByRole("checkbox", { name: item.text });
  expect((checkbox as HTMLInputElement).checked).toBe(false);
  expect(screen.getByText("적용 조건: A server is operated.")).toBeTruthy();
  fireEvent.click(checkbox);
  expect(screen.getByTestId("selection").textContent).toBe(JSON.stringify([{ id: item.id, version: 1, source_hash: item.source_hash }]));
  fireEvent.change(screen.getByLabelText("프로젝트"), { target: { value: "" } });
  expect(screen.getByTestId("selection").textContent).toBe("[]");
  expect(post).not.toHaveBeenCalled();
});

it("이전 프로젝트의 늦은 응답을 폐기하고 출처가 없는 결정은 선택하지 못한다", async () => {
  let resolve!: (value: unknown) => void;
  vi.mocked(api).mockImplementation(async path => path === "/api/projects" ? [{ id: "project", name: "첫 프로젝트" }, { id: "second", name: "다음 프로젝트" }] : path.includes("/project/") ? new Promise(r => { resolve = r; }) : { ...packet, rows: [{ ...item, source_available: false }] });
  render(<Harness />); await screen.findByRole("option", { name: "첫 프로젝트" });
  fireEvent.change(screen.getByLabelText("프로젝트"), { target: { value: "project" } });
  fireEvent.click(screen.getByRole("button", { name: "공통 결정 선택 · 0개" }));
  fireEvent.change(screen.getByLabelText("프로젝트"), { target: { value: "second" } });
  fireEvent.click(screen.getByRole("button", { name: "공통 결정 선택 · 0개" }));
  await screen.findByRole("checkbox");
  expect((screen.getByRole("checkbox") as HTMLInputElement).disabled).toBe(true);
  await act(async () => resolve(packet));
  expect(screen.getByText("출처 확인 불가")).toBeTruthy();
});

it("개인 프로젝트 생성 후 해당 프로젝트로 이동한다", async () => {
  vi.mocked(api).mockImplementation(async path => path === "/api/projects" ? [] : { ...packet, rows: [] });
  vi.mocked(post).mockResolvedValue({ id: "created", name: "새 프로젝트" });
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "프로젝트 만들기" }));
  const dialog = screen.getByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("프로젝트 이름"), { target: { value: "새 프로젝트" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "프로젝트 생성" }));
  await waitFor(() => expect(post).toHaveBeenCalledWith("/api/projects", { name: "새 프로젝트" }));
  await screen.findByRole("option", { name: "새 프로젝트" });
  expect((screen.getByLabelText("프로젝트") as HTMLSelectElement).value).toBe("created");
});

it("출처를 확인한 등록만 제출하고 연속 클릭을 중복 전송하지 않는다", async () => {
  vi.mocked(api).mockResolvedValue(packet);
  let resolve!: (value: unknown) => void;
  vi.mocked(post).mockImplementation(() => new Promise(r => { resolve = r; }));
  render(<MemoryRouter><ApprovedDecisions jobId="job" completedId={item.completed_id} /></MemoryRouter>);
  expect(api).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "승인본의 공통 결정 등록" }));
  fireEvent.click(await screen.findByRole("button", { name: "공통 결정으로 등록" }));
  const confirm = within(screen.getByRole("dialog")).getByRole("button", { name: "이 원문과 조건을 등록" });
  fireEvent.click(confirm); fireEvent.click(confirm);
  expect(post).toHaveBeenCalledTimes(1);
  expect(post).toHaveBeenCalledWith("/api/projects/project/decisions", { job_id: "job", completed_id: item.completed_id, decision_id: "DEC-DB", source_hash: item.source_hash });
  await act(async () => resolve(item));
  expect(screen.getByText(/프로젝트 공통 결정으로 등록했습니다/)).toBeTruthy();
});

it("등록 해제 후 선택을 지우고 과거 재사용 사본을 별도로 조회한다", async () => {
  vi.mocked(api).mockImplementation(async path => path === "/api/projects" ? [{ id: "project", name: "기록 서비스" }] : packet);
  vi.mocked(post).mockResolvedValue({ active: false, version: 2 });
  const view = render(<Harness />); await screen.findByRole("option", { name: "기록 서비스" });
  fireEvent.change(screen.getByLabelText("프로젝트"), { target: { value: "project" } });
  fireEvent.click(screen.getByRole("button", { name: "공통 결정 선택 · 0개" }));
  fireEvent.click(await screen.findByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "등록 해제" }));
  await waitFor(() => expect(screen.getByTestId("selection").textContent).toBe("[]"));
  view.unmount();
  render(<MemoryRouter><ReusedDecisions jobId="job" count={1} /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "이번 요청에 재사용한 결정 1개" }));
  await screen.findByText(item.text);
  expect(api).toHaveBeenLastCalledWith("/api/jobs/job/reused-decisions?offset=0", expect.anything());
});

it("조회 실패를 표시하고 다시 조회할 수 있다", async () => {
  vi.mocked(api).mockImplementation(async path => { if (path === "/api/projects") return [{ id: "project", name: "기록 서비스" }]; throw new Error("조회 실패"); });
  render(<Harness />); await screen.findByRole("option", { name: "기록 서비스" });
  fireEvent.change(screen.getByLabelText("프로젝트"), { target: { value: "project" } });
  fireEvent.click(screen.getByRole("button", { name: "공통 결정 선택 · 0개" }));
  await screen.findByRole("alert");
  vi.mocked(api).mockResolvedValue({ ...packet, rows: [] });
  fireEvent.click(screen.getByRole("button", { name: "다시 조회" }));
  await screen.findByText("등록된 공통 결정이 없습니다");
});

it("프로젝트 생성 중 닫으면 늦은 응답으로 프로젝트를 자동 선택하지 않는다", async () => {
  vi.mocked(api).mockResolvedValue([]);
  let resolve!: (value: unknown) => void;
  vi.mocked(post).mockImplementation(() => new Promise(r => { resolve = r; }));
  render(<Harness />);
  fireEvent.click(screen.getByRole("button", { name: "프로젝트 만들기" }));
  const dialog = screen.getByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("프로젝트 이름"), { target: { value: "비동기 프로젝트" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "프로젝트 생성" }));
  fireEvent.click(within(dialog).getByRole("button", { name: "닫기" }));
  await act(async () => resolve({ id: "late", name: "비동기 프로젝트" }));
  expect((screen.getByLabelText("프로젝트") as HTMLSelectElement).value).toBe("");
});

it("등록 중 닫은 대화상자를 늦은 응답으로 다시 열거나 완료 안내로 바꾸지 않는다", async () => {
  vi.mocked(api).mockResolvedValue(packet);
  let resolve!: (value: unknown) => void;
  vi.mocked(post).mockImplementation(() => new Promise(r => { resolve = r; }));
  render(<MemoryRouter><ApprovedDecisions jobId="job" completedId={item.completed_id} /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: "승인본의 공통 결정 등록" }));
  fireEvent.click(await screen.findByRole("button", { name: "공통 결정으로 등록" }));
  const dialog = screen.getByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "이 원문과 조건을 등록" }));
  fireEvent.click(within(dialog).getByRole("button", { name: "닫기" }));
  await act(async () => resolve(item));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.queryByText(/프로젝트 공통 결정으로 등록했습니다/)).toBeNull();
});
