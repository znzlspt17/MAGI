import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Licenses } from "./Licenses";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("인증 API 없이 정적 고지를 읽고 원문과 다운로드 링크를 제공한다", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => [{ name: "fixture", version: "1.0", license: "MIT", url: "https://example.com/source", text: "Copyright fixture\nPermission granted" }] });
  vi.stubGlobal("fetch", fetcher);
  render(<Licenses />);
  await screen.findByText("fixture");
  expect(fetcher.mock.calls[0][0]).toBe("/static/vendor/third-party-licenses.json");
  expect(screen.getByRole("link", { name: "전체 고지 다운로드" }).getAttribute("href")).toBe("/static/vendor/THIRD_PARTY_NOTICES.txt");
  expect(screen.getByText(/Copyright fixture/)).toBeTruthy();
});

it("고지 파일 응답 실패를 사용자에게 알린다", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
  render(<Licenses />);
  await waitFor(() => expect(screen.getByRole("status").textContent).toContain("불러오지 못했습니다"));
});
