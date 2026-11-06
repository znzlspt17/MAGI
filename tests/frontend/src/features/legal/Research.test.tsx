import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Research } from "@/features/legal/Research";
import { LoginForm } from "@/features/auth/LoginForm";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("네트워크 요청 없이 논문 출처와 적용 범위를 표시한다", () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  render(<Research />);
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("연구 출처 및 적용 방식");
  expect(screen.getAllByText(/RubricRefine: Improving Tool-Use Agent Reliability/).length).toBeGreaterThan(0);
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

it("보고서 목차가 모든 본문 절에 연결되고 비교 표와 출처를 제공한다", () => {
  render(<Research />);
  const navigation = screen.getByRole("navigation", { name: "보고서 목차" });
  const links = Array.from(navigation.querySelectorAll<HTMLAnchorElement>('a[href^="#"]'));
  expect(links).toHaveLength(12);
  for (const link of links) {
    const id = link.hash.slice(1);
    const target = document.getElementById(id);
    expect(target?.tagName).toBe("H2");
    expect(target?.textContent).toContain(link.textContent?.trim());
  }
  expect(screen.getByRole("table", { name: "논문과 MAGI 적용 비교" })).toBeTruthy();
  expect(screen.getByRole("table", { name: "MAGI 점수 상한" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: /가상의 예시: 8/ })).toBeTruthy();
  expect(screen.getByRole("heading", { name: /8.*7.*7/ })).toBeTruthy();
  const references = screen.getAllByRole("link").filter((link) => link.getAttribute("href")?.startsWith("https://arxiv.org/html/2605.09730v5#"));
  expect(references.length).toBeGreaterThanOrEqual(3);
});


it("점수 상한과 보완 흐름에 판단 불가·사용자 결정 대기를 표시한다", () => {
  render(<Research />);
  const scoreTable = screen.getByRole("table", { name: "MAGI 점수 상한" });
  expect(within(scoreTable).getByRole("rowheader", { name: /critical 항목.*판단 불가/ })).toBeTruthy();
  const loop = screen.getByLabelText("명세 평가와 후보 선택 의사코드").textContent || "";
  expect(loop).toMatch(/미응답.*사용자.*대기/);
  expect(loop).toMatch(/확정 근거.*바뀌면.*재평가/);
});

it("모델 점수의 서버 보정과 구조 검증을 구분해 설명한다", () => {
  render(<Research />);
  const score = document.getElementById("score")?.parentElement;
  expect(score?.textContent).toMatch(/모델이 제안한 점수.*가장 낮은 상한.*최종 점수/);
  expect(score?.textContent).toMatch(/중요 실패 목록.*서버가.*재구성/);
  expect(score?.textContent).toMatch(/인용.*연결.*맞지 않으면.*거부/);
});
