// 2026-11-15: 실제 공유 쿠키와 탭 간 잠금을 사용해 최초 익명 발급 경합을 검사한다.
import { createRequire } from "node:module";
import { createServer } from "node:http";
import { readFile, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import assert from "node:assert/strict";

const root = process.cwd();
const require = createRequire(join(root, "frontend/package.json"));
const { build } = await import(pathToFileURL(require.resolve("vite")).href);
const tailwind = (await import(pathToFileURL(require.resolve("@tailwindcss/vite")).href)).default;
const { chromium } = require("playwright");
const dist = await mkdtemp(join(tmpdir(), "magi-guest-qa-"));
let server, browser;
try {
  await build({ configFile: false, root: join(root, "frontend"), envDir: false, logLevel: "error", plugins: [tailwind()],
    resolve: { alias: { "@": join(root, "frontend/src") } }, base: "/static/dist/",
    build: { outDir: dist, emptyOutDir: false, manifest: "manifest.json", rollupOptions: { input: join(root, "frontend/src/main.tsx") } } });
  const manifest = JSON.parse(await readFile(join(dist, "manifest.json"), "utf8"))["src/main.tsx"];
  let issued = 0, requests = 0, missing = 0;
  const initialChecks = [];
  server = createServer(async (request, response) => {
    const path = new URL(request.url, "http://localhost").pathname;
    const json = (status, value, headers = {}) => { response.writeHead(status, { "Content-Type": "application/json", ...headers }); response.end(JSON.stringify(value)); };
    const sid = (request.headers.cookie || "").match(/sid=(g\d+)/)?.[1];
    if (path.startsWith("/static/dist/")) {
      try { const file = join(dist, path.slice("/static/dist/".length)); const content = await readFile(file); response.writeHead(200, { "Content-Type": file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" : "application/octet-stream" }); response.end(content); }
      catch { response.writeHead(404); response.end(); }
    } else if (path === "/api/auth/info") json(200, { public: true, login_available: false });
    else if (path === "/api/me") {
      if (sid) json(200, { id: sid, role: "user", csrf: sid, identity_kind: "guest", owner_ids: [sid] });
      else if (++missing <= 2) {
        initialChecks.push(() => json(401, { error: "로그인이 필요합니다." }));
        if (initialChecks.length === 2) initialChecks.forEach(finish => finish());
      } else json(401, { error: "로그인이 필요합니다." });
    }
    else if (path === "/api/auth/guest") { requests++; const id = sid || `g${++issued}`; await new Promise(resolve => setTimeout(resolve, 400)); json(200, { ok: true }, { "Set-Cookie": `sid=${id}; Path=/; HttpOnly; SameSite=Lax` }); }
    else if (path === "/api/service/status") json(200, { ready: true, active_count: 0, queued_count: 0, max_parallel: 100, own_active_count: 0 });
    else if (path === "/api/me/usage") json(200, { limit_mode: "observe", daily_runs: 0, runs_exceeded: false, runs: 0, remaining_runs: 0, resets_at: "", limit_reached: false });
    else if (path === "/api/jobs" || path === "/api/projects") json(200, []);
    else { response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" }); response.end(`<html><head>${(manifest.css || []).map(css => `<link rel="stylesheet" href="/static/dist/${css}">`).join("")}</head><body><div id="root"></div><script type="module" src="/static/dist/${manifest.file}"></script></body></html>`); }
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  browser = await chromium.launch({ headless: true, channel: process.platform === "win32" ? "msedge" : undefined });
  const context = await browser.newContext();
  await context.addInitScript(() => { window.WebSocket = class { static OPEN = 1; readyState = 0; constructor() { setTimeout(() => { this.readyState = 1; this.onopen?.({}); }, 0); } send() {} close() { this.readyState = 3; } }; });
  const a = await context.newPage(), b = await context.newPage();
  const base = `http://127.0.0.1:${server.address().port}`;
  await Promise.all([a.goto(base), b.goto(base)]);
  await Promise.all([a.getByText("새 명세 만들기").waitFor(), b.getByText("새 명세 만들기").waitFor()]);
  assert.equal(issued, 1, "동시 방문은 하나의 익명 작업 공간을 사용해야 한다");
  assert.equal((await context.cookies()).find(cookie => cookie.name === "sid")?.value, "g1");
  await context.close();
  const blocked = await browser.newContext();
  await blocked.addInitScript(() => Object.defineProperty(navigator, "locks", { value: undefined }));
  const page = await blocked.newPage(); const before = requests;
  await page.goto(base); await page.getByRole("alert").getByText(/브라우저/).waitFor();
  assert.equal(requests, before, "잠금이 없으면 익명 세션을 발급하면 안 된다");
  await blocked.close();
  console.log("anonymous tabs and unsupported locks passed");
} finally {
  await browser?.close();
  if (server) await new Promise(resolve => server.close(resolve));
  await rm(dist, { recursive: true, force: true });
}
