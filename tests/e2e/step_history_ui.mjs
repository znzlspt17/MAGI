import { createRequire } from 'node:module';
import { join } from 'node:path';
import { mkdirSync } from 'node:fs';
import assert from 'node:assert/strict';

const { chromium } = createRequire(join(process.argv[2], 'package.json'))('playwright');
const browser = await chromium.launch({ headless: true, channel: process.platform === 'win32' ? 'msedge' : undefined });
const ids = JSON.parse(process.argv[5]);
try {
  mkdirSync('.cache/step-history-preview', { recursive: true });
  for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
    const page = await browser.newPage({ viewport: { width, height } }), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      window.WebSocket = class { constructor() { queueMicrotask(() => this.onopen?.({})); } close() {} };
    });
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(`${process.argv[3]}/jobs/${process.argv[4]}`);
    await page.getByRole('tab', { name: '실행 이력', exact: true }).click();
    await page.getByRole('button', { name: /하위 처리 단계/ }).click();
    let releaseDetail;
    const detailGate = new Promise(resolve => { releaseDetail = resolve; });
    await page.route(`**/steps/${ids[0]}`, async route => { await detailGate; await route.continue(); }, { times: 1 });
    const indices = name === 'desktop' ? ids.map((_, i) => i) : [0, 1, 30];
    for (const index of indices) {
      const button = page.locator(`button[aria-controls="step-detail-${ids[index]}"]`);
      await button.click();
      const panel = page.locator(`[id="step-detail-${ids[index]}"]`);
      if (index === 0) {
        await panel.getByRole('status').getByText(/불러오는/).waitFor({ state: 'visible' });
        releaseDetail();
      }
      const text = index % 2 === 0 ? `판단 근거 ${index}` : `해결 판단 ${index}`;
      await panel.getByText(text).first().waitFor({ state: 'visible' });
      if (index % 2) {
        await panel.getByText(`결함 ${index}`, { exact: true }).waitFor({ state: 'visible' });
        assert(await panel.getByText('재사용한 답변: Q1').isVisible());
        assert(await panel.getByRole('button', { name: '이 단계의 명세 문서 보기' }).isVisible());
      }
      assert.equal(await page.locator('.execution-step-detail').count(), 1);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    }
    await page.screenshot({ path: `.cache/step-history-preview/${name}.png`, fullPage: true });
    await page.route(`**/steps/${ids[1]}`, route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: '검증용 조회 실패' }) }), { times: 1 });
    await page.locator(`button[aria-controls="step-detail-${ids[1]}"]`).click();
    await page.locator(`[id="step-detail-${ids[1]}"]`).getByText(/기록 확인 불가: 검증용 조회 실패/).waitFor({ state: 'visible' });
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log('31 DB snapshots → step API → desktop/mobile UI: passed');
} finally {
  await browser.close();
}
