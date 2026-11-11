import {createRef} from "react";
import {cleanup, render, screen} from "@testing-library/react";
import {afterEach, expect, it} from "vitest";
import {Textarea} from "@/shared/ui/textarea";
afterEach(cleanup);
it("여러 줄 입력의 원래 길이 제한과 ref를 유지한다", () => {
  const ref = createRef<HTMLTextAreaElement>();
  render(<Textarea aria-label="의견" maxLength={4000} ref={ref} />);
  const input = screen.getByRole("textbox", {name: "의견"}) as HTMLTextAreaElement;
  expect(input.maxLength).toBe(4000);
  expect(ref.current).toBe(input);
});
