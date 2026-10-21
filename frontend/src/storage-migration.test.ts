import { beforeEach, expect, it, vi } from "vitest";
import { migrateSessionKeys } from "./storage-migration";

beforeEach(() => sessionStorage.clear());
it("moves known keys without modifying draft content and is repeatable", () => {
  sessionStorage.setItem("magi:draft:owner", "magi:user supplied content");
  sessionStorage.setItem("magi:return-path", "/jobs/one");
  sessionStorage.setItem("magi:unrelated", "keep");
  migrateSessionKeys(sessionStorage);
  migrateSessionKeys(sessionStorage);
  expect(sessionStorage.getItem("draft:owner")).toBe("magi:user supplied content");
  expect(sessionStorage.getItem("return-path")).toBe("/jobs/one");
  expect(sessionStorage.getItem("magi:draft:owner")).toBeNull();
  expect(sessionStorage.getItem("magi:unrelated")).toBe("keep");
});
it("preserves both conflicting values", () => {
  sessionStorage.setItem("magi:draft:owner", "old");
  sessionStorage.setItem("draft:owner", "new");
  migrateSessionKeys(sessionStorage);
  expect(sessionStorage.getItem("magi:draft:owner")).toBe("old");
  expect(sessionStorage.getItem("draft:owner")).toBe("new");
});
it("does not restore a deliberately cleared conflicting draft on reload", () => {
  sessionStorage.setItem("magi:draft:owner", "old");
  sessionStorage.setItem("draft:owner", "new");
  migrateSessionKeys(sessionStorage);
  sessionStorage.removeItem("draft:owner");
  migrateSessionKeys(sessionStorage);
  expect(sessionStorage.getItem("draft:owner")).toBeNull();
  expect(sessionStorage.getItem("magi:draft:owner")).toBe("old");
});
it("retains old content if writing fails", () => {
  sessionStorage.setItem("magi:draft:owner", "keep");
  const storage = { length: 1, key: () => "magi:draft:owner", getItem: (key: string) => sessionStorage.getItem(key),
    setItem: vi.fn(() => { throw new Error("quota"); }), removeItem: vi.fn() } as unknown as Storage;
  migrateSessionKeys(storage);
  expect(sessionStorage.getItem("magi:draft:owner")).toBe("keep");
  expect(storage.removeItem).not.toHaveBeenCalled();
});
