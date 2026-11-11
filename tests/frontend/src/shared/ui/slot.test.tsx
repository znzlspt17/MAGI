import { createRef } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { AstryxSlot } from "@/shared/ui/astryx-slot";
afterEach(cleanup);
it("자식 이벤트를 먼저 실행하고 취소된 이벤트는 부모로 전달하지 않는다", () => {
  const calls: string[] = [];
  render(<AstryxSlot onClick={() => calls.push("parent")}><button onClick={event => { calls.push("child"); event.preventDefault(); }}>열기</button></AstryxSlot>);
  fireEvent.click(screen.getByRole("button", { name: "열기" }));
  expect(calls).toEqual(["child"]);
});
it("취소되지 않은 이벤트는 자식 다음 부모 순서로 실행한다", () => {
  const calls: string[] = [];
  render(<AstryxSlot onClick={() => calls.push("parent")}><button onClick={() => calls.push("child")}>열기</button></AstryxSlot>);
  fireEvent.click(screen.getByRole("button", { name: "열기" }));
  expect(calls).toEqual(["child", "parent"]);
});
it("클래스와 스타일 및 양쪽 ref를 결합하고 ref cleanup을 호출한다", () => {
  const parent = createRef<HTMLElement>(); const cleanupRef = vi.fn();
  const child = vi.fn((node: HTMLButtonElement | null) => node ? cleanupRef : undefined);
  const view = render(<AstryxSlot ref={parent} className="parent" style={{ color: "red", padding: 4 }}><button ref={child} className="child" style={{ color: "blue" }}>열기</button></AstryxSlot>);
  const button = screen.getByRole("button", { name: "열기" });
  expect(button.className).toContain("parent"); expect(button.className).toContain("child");
  expect(button.style.color).toBe("blue"); expect(button.style.padding).toBe("4px"); expect(parent.current).toBe(button);
  view.unmount(); expect(cleanupRef).toHaveBeenCalledOnce(); expect(parent.current).toBeNull();
});
