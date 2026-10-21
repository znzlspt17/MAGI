import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { ChangeReview } from "./ChangeReview";
import type { ChangeReviewData, SpecChange } from "./types";

afterEach(cleanup);
const location = { item_id: "B", section: "## Storage", text: "Store per account.", start: 0, end: 18, line: 3, requirement_ids: [], decision_ids: [] };
const change: SpecChange = { id: "C", change: "modified", before: location, after: { ...location, text: "Store per device." },
  status: "analysed", reason: "", meaning: "semantic", relation: "unverified", summary: "기기별 저장으로 변경했습니다.",
  rationale: "로그인 해제 요청은 저장 방식을 확정하지 않습니다.", question: "다른 기기에서도 기록을 이어서 봐야 하나요?", diff: "- Store per account.\n+ Store per device." };
const review: ChangeReviewData = { status: "complete", before_id: "old", after_id: "new", after_hash: "hash", analysed: 1, remaining: 0, sources: [], changes: [change] };

describe("승인 전 변경 검토", () => {
  it("요청 반영과 함께 바뀐 내용을 분리하고 원문과 근거를 접어 표시한다", () => {
    const direct: SpecChange = { ...change, id: "AUTH", relation: "direct", summary: "로그인 필수 조건을 제거했습니다.", question: "",
      evidence: [{ source_id: "input", quote: "로그인 없이 사용" }] };
    render(<ChangeReview review={{ ...review, analysed: 2, changes: [direct, change], sources: [{ source_id: "input", text: "로그인 없이 사용" }] }} />);
    expect(screen.getByRole("heading", { name: "요청 반영" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "함께 달라진 내용" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "확인할 사항" })).toBeTruthy();
    const detail = screen.getByText("기기별 저장으로 변경했습니다.").closest("details")!;
    expect(detail.open).toBe(false);
    fireEvent.click(detail.querySelector("summary")!);
    expect(within(detail).getByText("Store per account.")).toBeTruthy();
    expect(within(detail).getByText("Store per device.")).toBeTruthy();
    expect(within(detail).getAllByText("## Storage · 3행")).toHaveLength(2);
  });

  it("질문은 수정 의견으로 연결하고 표현 변경은 접어 둔다", () => {
    const select = vi.fn();
    render(<ChangeReview review={{ ...review, changes: [change, { ...change, id: "W", meaning: "wording", question: "" }] }} onQuestion={select} />);
    fireEvent.click(screen.getByRole("button", { name: "수정 의견에 추가" }));
    expect(select).toHaveBeenCalledWith(change.question);
    expect(screen.getByText("표현만 달라진 내용 1건").closest("details")?.open).toBe(false);
  });

  it.each(["partial", "failed", "running"] as const)("%s 상태의 미분석을 숨기지 않는다", status => {
    render(<ChangeReview review={{ ...review, status, analysed: 0, remaining: 1, changes: [{ ...change, meaning: undefined, status: "unanalysed", reason: "context_limit", summary: undefined }] }} />);
    expect(screen.getByRole("status").textContent).toContain("1건 미분석");
    expect(screen.getByText(/원문을 확인한 후 승인할 수 있습니다/)).toBeTruthy();
    expect(screen.getByText(/입력 한도를 넘어 판단을 보류/)).toBeTruthy();
  });

  it("최초 후보와 변경 없음을 구별한다", () => {
    const view = render(<ChangeReview review={{ ...review, status: "no_baseline", changes: [], analysed: 0 }} />);
    expect(screen.getByText(/첫 승인 후보입니다/)).toBeTruthy();
    view.rerender(<ChangeReview review={{ ...review, status: "unchanged", changes: [], analysed: 0 }} />);
    expect(screen.getByText(/의미의 안전성을 보증하는 결과는 아닙니다/)).toBeTruthy();
  });
});
