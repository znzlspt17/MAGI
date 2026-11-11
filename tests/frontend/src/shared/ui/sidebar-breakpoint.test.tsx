import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useIsMobile } from "@/shared/hooks/use-mobile";

function Probe() { return <span>{useIsMobile() ? "서랍" : "고정 탐색"}</span>; }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("태블릿 1024px에서는 탐색을 서랍으로 제공한다", () => {
  vi.stubGlobal("innerWidth", 1024);
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })));
  render(<Probe />);
  expect(screen.getByText("서랍")).toBeTruthy();
});
