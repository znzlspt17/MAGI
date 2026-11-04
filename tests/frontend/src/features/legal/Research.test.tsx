import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Research } from "@/features/legal/Research";
import { LoginForm } from "@/features/auth/LoginForm";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("네트워크 요청 없이 논문 출처와 적용 범위를 표시한다", () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  render(<Research />);
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("연구 출처 및 적용 방식");
  expect(screen.getByText(/RubricRefine: Improving Tool-Use Agent Reliability/)).toBeTruthy();
  expect(screen.getByText(/Will LeVine, Brendan Raffel Evers, Sam Saltwick, Abhay Venkatesh/)).toBeTruthy();
  expect(screen.getByText("2026년 · arXiv:2605.09730v5")).toBeTruthy();
  expect(screen.getByRole("link", { name: /논문 원문/ }).getAttribute("href")).toBe("https://arxiv.org/html/2605.09730v5");
  expect(screen.getByText(/충족·미충족·판단 불가로 판정/)).toBeTruthy();
  expect(screen.getByText(/정확성이나 요구사항의 완전성을 보장하지/)).toBeTruthy();
  for (const href of ["/", "/privacy", "/licenses"]) {
    expect(screen.getAllByRole("link").some((link) => link.getAttribute("href") === href)).toBe(true);
  }
  expect(fetcher).not.toHaveBeenCalled();
});

it("로그인을 사용할 수 없어도 연구 안내 진입점을 제공한다", () => {
  render(<LoginForm available={false} notice="" />);
  expect(screen.getByRole("link", { name: "연구 출처 및 적용 방식" }).getAttribute("href")).toBe("/research");
});
