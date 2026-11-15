import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DraftRecovery } from "@/features/conversation/DraftRecovery";

afterEach(() => { cleanup(); sessionStorage.clear(); });
it("같은 입력의 이전 내용을 고르면 현재 내용도 백업으로 보존한다", () => {
  sessionStorage.setItem("draft:user", "현재");
  sessionStorage.setItem("draft-backup:draft:user", "이전");
  sessionStorage.setItem("draft-backup:draft:other", "다른 사용자");
  const onRestore = vi.fn();
  render(<DraftRecovery draftKey="draft:user" onRestore={onRestore} />);
  expect(screen.queryByText("다른 사용자")).toBeNull();
  fireEvent.click(screen.getByText("이전 작성 내용 복구 (1)"));
  fireEvent.click(screen.getByText("이 내용 복구"));
  expect(onRestore).toHaveBeenCalledWith("이전");
  expect(sessionStorage.getItem("draft:user")).toBe("이전");
  expect(sessionStorage.getItem("draft-backup:draft:user:1")).toBe("현재");
});
it("다른 작업과 질문 버전 및 손상된 구조화 백업을 표시하지 않는다", () => {
  sessionStorage.setItem("draft-backup:draft:user:job:question:version:1:1", JSON.stringify({ text: "유효" }));
  sessionStorage.setItem("draft-backup:draft:user:job:question:other", JSON.stringify({ text: "다른 버전" }));
  sessionStorage.setItem("draft-backup:draft:user:job:question:version:2", "잘못된 형식");
  render(<DraftRecovery draftKey="draft:user:job:question:version" onRestore={() => {}} describe={value => {
    try { const parsed = JSON.parse(value); return typeof parsed.text === "string" ? parsed.text : null; } catch { return null; }
  }} />);
  expect(screen.getByText("이전 작성 내용 복구 (1)")).toBeTruthy();
  expect(screen.queryByText("다른 버전")).toBeNull();
  expect(screen.queryByText("잘못된 형식")).toBeNull();
});
