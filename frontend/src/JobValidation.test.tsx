import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import JobValidation, { type ValidationRecord } from "./JobValidation";
vi.mock("./api", () => ({ api: vi.fn() }));
const id = "a".repeat(32), execution = "c".repeat(32);
const record: ValidationRecord = { record_id: "record", created_at: "2026-10-27T17:23:58+09:00", execution_id: null,
  execution_link: "unconfirmed", state: "recognized", stage: "spec_compile", error_code: "SPEC_COMPILATION_INVALID", failed_checks: ["spec_blocks"],
  attempt: 4, validation_reason: "empty_section", validation_section: "out_of_scope", validation_index: null };
const page = (items = [record], next: number | null = null) => ({ items, offset: 0, limit: 20, next_offset: next });
beforeEach(() => { vi.mocked(api).mockResolvedValue(page()); });
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("과거 기록의 안전한 사유·KST와 연결 미확인을 표시한다", async () => {
  render(<JobValidation jobId={id} />);
  await screen.findByText("섹션에 내용 블록이 없습니다");
  expect(screen.getByText("실행 연결 미확인")).toBeVisible();
  expect(screen.getByText("비범위")).toBeVisible();
  expect(screen.getByText(/26\. 10\. 27\. 17:23 KST/)).toBeVisible();
  const link = screen.getByRole("link", { name: "관련 로그 보기" });
  const url = new URL(link.getAttribute("href")!, "http://localhost");
  expect(url.searchParams.get("job_id")).toBe(id);
  expect(url.searchParams.get("execution_id")).toBeNull();
  expect(url.searchParams.get("period")).toBe("10080");
});

it("연결된 실행만 로그 필터에 넣고 페이지를 이동한다", async () => {
  vi.mocked(api).mockResolvedValueOnce(page([{ ...record, execution_id: execution, execution_link: "confirmed", validation_index: 2 }], 20)).mockResolvedValueOnce({ ...page([]), offset: 20 });
  render(<JobValidation jobId={id} />); await screen.findByText("3번째 블록");
  expect(screen.getByRole("link", { name: "관련 로그 보기" }).getAttribute("href")).toContain("execution_id=" + execution);
  fireEvent.click(screen.getByRole("button", { name: "다음 진단" }));
  await screen.findByText("저장된 명세 검증 기록이 없습니다.");
  expect(vi.mocked(api).mock.calls.at(-1)?.[0]).toContain("offset=20");
});

it("손상·해석 불가·빈 결과와 조회 오류를 구분하고 재조회한다", async () => {
  vi.mocked(api).mockRejectedValueOnce(new Error("진단 조회 실패")).mockResolvedValueOnce(page([{ ...record, state: "unreadable", validation_reason: null }]));
  render(<JobValidation jobId={id} />); await screen.findByRole("alert");
  expect(screen.queryByText("저장된 명세 검증 기록이 없습니다.")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "진단 다시 조회" }));
  await screen.findByText("세부 사유 판별 불가");
  expect(screen.getByText("저장된 진단 형식을 해석할 수 없습니다. 원문은 표시하지 않습니다.")).toBeVisible();
});

it("다른 작업으로 전환한 뒤 이전 작업의 늦은 응답을 버린다", async () => {
  let finish: (value: unknown) => void = () => {};
  vi.mocked(api).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce(page([]));
  const view = render(<JobValidation key={id} jobId={id} />);
  view.rerender(<JobValidation key="other" jobId={"b".repeat(32)} />);
  await screen.findByText("저장된 명세 검증 기록이 없습니다.");
  await act(async () => finish(page()));
  expect(screen.queryByText("섹션에 내용 블록이 없습니다")).toBeNull();
});
