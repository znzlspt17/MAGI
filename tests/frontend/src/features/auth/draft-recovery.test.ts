import { beforeEach, expect, it, vi } from "vitest";
import * as drafts from "@/features/conversation/session-drafts";

beforeEach(() => sessionStorage.clear());
it("선택한 백업을 복원할 때 현재 초안과 다른 백업을 보존한다", () => {
  sessionStorage.setItem("draft:owner", "현재");
  sessionStorage.setItem("draft-backup:draft:owner", "이전");
  sessionStorage.setItem("draft-backup:draft:owner:1", "다른 초안");
  const restore = (drafts as unknown as { restoreDraft?: (storage: Storage, key: string, backup: string) => string }).restoreDraft;
  expect(restore).toBeTypeOf("function");
  expect(restore!(sessionStorage, "draft:owner", "draft-backup:draft:owner")).toBe("이전");
  expect(sessionStorage.getItem("draft:owner")).toBe("이전");
  expect(sessionStorage.getItem("draft-backup:draft:owner")).toBeNull();
  expect(sessionStorage.getItem("draft-backup:draft:owner:2")).toBe("현재");
  expect(sessionStorage.getItem("draft-backup:draft:owner:1")).toBe("다른 초안");
});
it("브라우저 저장소가 막혀도 작성 화면에서 예외가 나지 않는다", () => {
  const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
  const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
  const remove = vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => { throw new Error("blocked"); });
  expect(drafts.draftStorage.getItem("draft:owner")).toBeNull();
  expect(() => drafts.draftStorage.setItem("draft:owner", "내용")).not.toThrow();
  expect(() => drafts.draftStorage.removeItem("draft:owner")).not.toThrow();
  get.mockRestore(); set.mockRestore(); remove.mockRestore();
});
it("삭제된 작업의 초안과 백업만 제거한다", () => {
  sessionStorage.setItem("draft:owner:job:message", "내용");
  sessionStorage.setItem("draft-backup:draft:owner:job:message:1", "이전");
  sessionStorage.setItem("draft-backup:draft:owner:other:message", "유지");
  const clear = (drafts as unknown as { clearJobDrafts?: (storage: Storage, owner: string, job: string) => void }).clearJobDrafts;
  expect(clear).toBeTypeOf("function");
  clear!(sessionStorage, "owner", "job");
  expect(sessionStorage.getItem("draft:owner:job:message")).toBeNull();
  expect(sessionStorage.getItem("draft-backup:draft:owner:job:message:1")).toBeNull();
  expect(sessionStorage.getItem("draft-backup:draft:owner:other:message")).toBe("유지");
});
it("계정 연결은 익명 초안과 그 이전 백업도 모두 옮긴다", () => {
  sessionStorage.setItem("draft:guest", "익명");
  sessionStorage.setItem("draft-backup:draft:guest", "익명의 이전 내용");
  sessionStorage.setItem("draft:owner", "계정 내용");
  drafts.copyAccountDrafts(sessionStorage, "guest", "owner");
  expect(sessionStorage.getItem("draft:owner")).toBe("익명");
  expect(Object.keys(sessionStorage).filter(key => key.startsWith("draft-backup:draft:owner")).map(key => sessionStorage.getItem(key))).toContain("익명의 이전 내용");
  expect(sessionStorage.getItem("draft-backup:draft:guest")).toBeNull();
});
