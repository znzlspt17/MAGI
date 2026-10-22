import { afterEach, expect, it, vi } from "vitest";
import { apiBlob, configureAuth } from "./api";
afterEach(() => { vi.unstubAllGlobals(); configureAuth({ publicMode: false }); });
it("ZIP 조회는 공개 모드 CSRF만 전송하고 중복 방지 키를 만들지 않는다", async () => {
  const blob = new Blob(["zip"]);
  const fetcher = vi.fn().mockResolvedValue({ ok: true, status: 200, headers: new Headers({ "Content-Type": "application/zip" }), blob: async () => blob });
  vi.stubGlobal("fetch", fetcher); configureAuth({ publicMode: true, csrf: "fake-csrf" });
  expect(await apiBlob("/download")).toBe(blob);
  expect(fetcher.mock.calls[0][1].headers.get("X-CSRF-Token")).toBe("fake-csrf");
  expect(fetcher.mock.calls[0][1].headers.has("Idempotency-Key")).toBe(false);
});
it("계정 전환 뒤 도착한 ZIP은 전달하지 않는다", async () => {
  let resolve!: (v: any) => void; vi.stubGlobal("fetch", vi.fn(() => new Promise(done => { resolve = done; })));
  const pending = apiBlob("/download"); configureAuth({ publicMode: true, csrf: "new" });
  resolve({ ok: true, status: 200 });
  await expect(pending).rejects.toThrow("계정이 변경");
});
