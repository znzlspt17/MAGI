import {createRef} from "react";
import {cleanup, fireEvent, render, screen} from "@testing-library/react";
import {afterEach, expect, it, vi} from "vitest";
import {Input} from "@/shared/ui/input";
afterEach(cleanup);
it("한 줄 입력은 ref와 입력 이벤트 및 길이 제한을 유지한다", () => {
  const ref = createRef<HTMLInputElement>(); const change = vi.fn();
  render(<Input aria-label="작업 ID" ref={ref} maxLength={8} onChange={change} />);
  const input = screen.getByRole("textbox", {name: "작업 ID"}) as HTMLInputElement;
  expect(ref.current).toBe(input); expect(input.maxLength).toBe(8);
  fireEvent.change(input, {target: {value: "abc"}}); expect(change).toHaveBeenCalledOnce();
});
it("비활성 한 줄 입력은 native disabled 상태를 유지한다", () => {
  render(<Input aria-label="검색" disabled />);
  expect((screen.getByRole("textbox", {name: "검색"}) as HTMLInputElement).disabled).toBe(true);
});
it("필수 입력은 브라우저의 폼 검증에 참여한다", () => {
  render(<form aria-label="양식"><Input aria-label="작업 ID" required /></form>);
  expect((screen.getByRole("form", {name: "양식"}) as HTMLFormElement).checkValidity()).toBe(false);
});
