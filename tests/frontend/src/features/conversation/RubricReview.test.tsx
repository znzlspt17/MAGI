import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { RubricReview } from "@/features/conversation/RubricReview";
import type { RubricReview as Review } from "@/shared/types";

afterEach(cleanup);
const item = (n: number, verdict: Review["items"][number]["verdict"] = "PASS"): Review["items"][number] => ({
  rubric_id: `RUB-${n}`, requirement_id: `REQ-${n}`, condition: `평가 조건 ${n}`, importance: "core",
  verdict, basis: [{ reference: "REQ-1", quote: `요구 원문 ${n}` }], reason: `판정 사유 ${n}`,
  section: "test_plan", quote: `명세 근거 ${n}`, evidence_kind: "quote",
});
const review = (items = [item(1)]): Review => ({ score: 10, score_reason: "평가 설명", round: 3, selected_round: 2, selected_cycle: 1,
  termination: "max_score", requires_acceptance: false, evaluation_hash: "one", revision_directives: [], remaining_issues: [], items });

it("집계와 상세를 나누고 한 번에 한 항목만 펼친다", () => {
  render(<RubricReview review={review([item(1), item(2)])} />);
  expect(screen.getByText("명세 평가 10/10")).toBeTruthy();
  expect(screen.getByText("충족 2")).toBeTruthy();
  expect(screen.queryByText("평가 조건 1")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /평가 항목 2개 보기/ }));
  fireEvent.click(screen.getByRole("button", { name: /RUB-1/ }));
  expect(screen.getByText("요구 원문 1")).toBeTruthy();
  expect(screen.getByText("테스트 계획")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /RUB-2/ }));
  expect(screen.queryByText("요구 원문 1")).toBeNull();
  expect(screen.getByText("요구 원문 2")).toBeTruthy();
});

it("미충족과 판단 보류를 우선 보여주고 결함과 근거 없음을 보존한다", () => {
  const missing = { ...item(3, "UNDETERMINED"), evidence_kind: "absence" as const, quote: "", section: "unknown_section" };
  const data = { ...review([item(1), item(2, "FAIL"), missing]), remaining_issues: [{ issue_id: "I1", severity: "major", problem: "결함", required_change: "보완" }], revision_directives: ["검증 조건을 수정하세요"] };
  render(<RubricReview review={data} />);
  expect(screen.getByText("결함")).toBeTruthy(); expect(screen.getByText("보완")).toBeTruthy(); expect(screen.getByText("검증 조건을 수정하세요")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: /평가 항목 3개 보기/ }));
  expect(screen.queryByText("평가 조건 1")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: /RUB-3/ }));
  expect(screen.getByText("해당 조건의 근거 없음")).toBeTruthy();
  expect(screen.getByText("unknown_section")).toBeTruthy();
});

it("검색과 페이지 이동 후 새 평가가 도착하면 탐색 상태를 초기화한다", () => {
  const data = review(Array.from({ length: 12 }, (_, index) => item(index + 1)));
  const { rerender } = render(<RubricReview review={data} />);
  fireEvent.click(screen.getByRole("button", { name: /평가 항목 12개 보기/ }));
  expect(screen.getByText("평가 조건 10")).toBeTruthy(); expect(screen.queryByText("평가 조건 11")).toBeNull();
  fireEvent.click(within(screen.getByRole("navigation", { name: "평가 항목 페이지" })).getByRole("button", { name: "다음" }));
  expect(screen.getByText("평가 조건 11")).toBeTruthy();
  fireEvent.change(screen.getByRole("searchbox", { name: "평가 항목 검색" }), { target: { value: "REQ-2" } });
  expect(screen.getByText("평가 조건 2")).toBeTruthy(); expect(screen.queryByText("평가 조건 11")).toBeNull();
  rerender(<RubricReview review={{ ...review([item(4, "FAIL")]), evaluation_hash: "two" }} />);
  fireEvent.click(screen.getByRole("button", { name: /평가 항목 1개 보기/ }));
  expect((screen.getByRole("searchbox", { name: "평가 항목 검색" }) as HTMLInputElement).value).toBe("");
  expect(screen.getByText("평가 조건 4")).toBeTruthy();
});

it("빈 목록과 검색 결과 없음에 안내를 표시한다", () => {
  const { rerender } = render(<RubricReview review={review([])} />);
  fireEvent.click(screen.getByRole("button", { name: /평가 항목 0개 보기/ }));
  expect(screen.getByText("표시할 평가 항목이 없습니다.")).toBeTruthy();
  rerender(<RubricReview review={{ ...review(), evaluation_hash: "new" }} />);
  fireEvent.click(screen.getByRole("button", { name: /평가 항목 1개 보기/ }));
  fireEvent.change(screen.getByRole("searchbox", { name: "평가 항목 검색" }), { target: { value: "없는 항목" } });
  expect(screen.getByText("검색 조건에 맞는 평가 항목이 없습니다.")).toBeTruthy();
});

it("평가 설명을 펼치면 평가 이력과 긴 설명 전체를 확인한다", () => {
  const reason = "긴 평가 설명입니다. ".repeat(20);
  render(<RubricReview review={{ ...review(), score_reason: reason }} />);
  expect(screen.queryByText(/10점 도달/)).toBeNull();
  expect(screen.getByText(reason.trim()).classList.contains("is-clamped")).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "평가 설명 보기" }));
  expect(screen.getByText(reason.trim()).classList.contains("is-clamped")).toBe(false);
  expect(screen.getByText(/10점 도달.*평가 3회.*1구간 2회차/)).toBeTruthy();
});

it("필터를 바꾸면 페이지와 펼친 항목이 초기화되고 인용 원문을 보존한다", () => {
  const longQuote = "원문의 줄바꿈과 긴 내용입니다.\n".repeat(25);
  const first = { ...item(1), basis: [{ reference: "custom_reference", quote: longQuote }] };
  render(<RubricReview review={review([first, ...Array.from({ length: 11 }, (_, i) => item(i + 2))])} />);
  fireEvent.click(screen.getByRole("button", { name: /평가 항목 12개 보기/ }));
  fireEvent.click(screen.getByRole("button", { name: /RUB-1 / }));
  expect(screen.getByText("custom_reference")).toBeTruthy();
  expect(screen.getByText("custom_reference").nextElementSibling?.textContent).toBe(longQuote);
  fireEvent.change(screen.getByRole("combobox", { name: "평가 판정 필터" }), { target: { value: "PASS" } });
  expect(screen.queryByText("custom_reference")).toBeNull();
  fireEvent.click(within(screen.getByRole("navigation", { name: "평가 항목 페이지" })).getByRole("button", { name: "다음" }));
  expect(screen.getByText("평가 조건 11")).toBeTruthy();
  fireEvent.change(screen.getByRole("combobox", { name: "평가 판정 필터" }), { target: { value: "all" } });
  expect(screen.getByText("평가 조건 1")).toBeTruthy();
  expect(screen.queryByText("평가 조건 11")).toBeNull();
});
