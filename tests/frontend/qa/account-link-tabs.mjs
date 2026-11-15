// 2026-11-13: 계정 연결 시 다른 탭의 초안과 명시적 로그아웃 정리를 실제 브라우저에서 확인한다.
import { createRequire } from 'node:module';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { join, extname } from 'node:path';
import assert from 'node:assert/strict';

const root = process.cwd();
const { chromium } = createRequire(join(root, 'frontend/package.json'))('playwright');
const dist = join(root, 'frontend/static/dist');
const manifest = JSON.parse(await readFile(join(dist, 'manifest.json'), 'utf8'))['src/main.tsx'];
const server = createServer(async (request, response) => {
  try {
    const path = new URL(request.url, 'http://localhost').pathname;
    if (path.startsWith('/static/dist/')) {
      const relative = path.slice('/static/dist/'.length);
      if (relative.includes('..')) throw new Error('invalid asset');
      const type = { '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' }[extname(relative)] || 'application/octet-stream';
      response.writeHead(200, { 'Content-Type': type });
      response.end(await readFile(join(dist, relative)));
    } else {
      response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
      response.end(`<html lang="ko"><head>${(manifest.css || []).map(css => `<link rel="stylesheet" href="/static/dist/${css}">`).join('')}</head><body><div id="root"></div><script type="module" src="/static/dist/${manifest.file}"></script></body></html>`);
    }
  } catch { response.writeHead(404); response.end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const base = `http://127.0.0.1:${server.address().port}`;
let browser;
try {
  browser = await chromium.launch({ headless: true, channel: process.platform === 'win32' ? 'msedge' : undefined });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(() => {
    window.__sockets = [];
    window.WebSocket = class {
      static OPEN = 1; readyState = 0;
      constructor() { window.__sockets.push(this); setTimeout(() => { if (this.readyState !== 3) { this.readyState = 1; this.onopen?.({}); } }, 0); }
      close() { this.readyState = 3; this.onclose?.({}); }
      send() {}
      emit(value) { this.onmessage?.({ data: JSON.stringify(value) }); }
    };
  });
  let session = 'guest';
  await context.route('**/auth/google/start', route => { session = 'google'; return route.fulfill({ status: 302, headers: { Location: '/?auth=linked' } }); });
  await context.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    let json;
    if (path === '/api/auth/info') json = { public: true, login_available: true };
    else if (path === '/api/auth/guest') { session = 'guest'; json = {}; }
    else if (path === '/api/logout') { session = 'expired'; json = {}; }
    else if (path === '/api/me' && session === 'expired') return route.fulfill({ status: 401, json: { error: '세션 만료' } });
    else if (path === '/api/me') json = session === 'google'
      ? { id: 'owner', role: 'user', csrf: 'owner-csrf', identity_kind: 'google', owner_ids: ['owner', 'guest'] }
      : { id: 'guest', role: 'user', csrf: 'guest-csrf', identity_kind: 'guest', owner_ids: ['guest'] };
    else if (path === '/api/me/usage') json = { runs: 0, remaining_runs: 3 };
    else if (path === '/api/service/status') json = { ready: true, active_count: 0, queued_count: 0, max_parallel: 100, own_active_count: 0 };
    else if (path === '/api/jobs' || path === '/api/projects') json = [];
    else throw new Error(`unexpected API: ${path}`);
    return route.fulfill({ json });
  });
  const first = await context.newPage(), second = await context.newPage();
  await Promise.all([first.goto(base), second.goto(base)]);
  const draft = second.getByRole('textbox', { name: '개발 요청', exact: true });
  await draft.fill('두 번째 탭의 작성 중인 요청');
  await second.waitForFunction(() => sessionStorage.getItem('draft:guest') === '두 번째 탭의 작성 중인 요청');
  await first.getByRole('link', { name: '로그인해서 기록 이어가기' }).click();
  await first.getByRole('button', { name: '내 계정' }).waitFor();
  await second.evaluate(() => window.__sockets.find(socket => socket.readyState === 1).emit({ event: 'session.expired' }));
  await second.getByRole('button', { name: '내 계정' }).waitFor();
  await second.waitForFunction(() => sessionStorage.getItem('draft:owner') === '두 번째 탭의 작성 중인 요청');
  assert.equal(await draft.inputValue(), '두 번째 탭의 작성 중인 요청');
  assert.equal(await second.evaluate(() => sessionStorage.getItem('draft:guest')), null);
  await second.getByRole('button', { name: '내 계정' }).click();
  await second.getByRole('menuitem', { name: '로그아웃' }).click();
  await second.getByRole('link', { name: '로그인해서 기록 이어가기' }).waitFor();
  assert.equal(await second.evaluate(() => sessionStorage.getItem('draft:owner')), null);
  assert.equal(await draft.inputValue(), '');
  console.log('account link tabs and logout passed');
} finally {
  await browser?.close();
  await new Promise(resolve => server.close(resolve));
}
