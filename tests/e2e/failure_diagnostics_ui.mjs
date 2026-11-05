import { createRequire } from 'node:module';
import { join } from 'node:path';
import assert from 'node:assert/strict';

// QA 응답을 이용해 운영 계정과 외부 모델에 접근하지 않는다.
const { chromium } = createRequire(join(process.argv[2], 'package.json'))('playwright');
const browser = await chromium.launch({ headless: true, channel: process.platform === 'win32' ? 'msedge' : undefined });
const url = `${process.argv[3]}/jobs/${'a'.repeat(32)}?role=admin&status=error`;
const reason = '검토에 사용한 인용을 해당 초안 섹션에서 찾지 못했습니다.';
try {
  for (const [width, height] of [[1440, 1000], [390, 844]]) {
    const page = await browser.newPage({ viewport: { width, height } }), errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      window.WebSocket = class { static OPEN = 1; readyState = 1; constructor() { queueMicrotask(() => this.onopen?.({})); } send() {} close() {} };
    });
    await page.goto(url);
    await page.getByRole('region', { name: '실패 진단' }).getByText(reason).first().waitFor({ state: 'visible' });
    await page.getByText('기술 진단 상세').click();
    assert(await page.getByText('검토 기준 참조: RUB-001').isVisible());
    assert(await page.getByText(/1회차/).isVisible());
    await page.getByRole('tab', { name: '명세', exact: true }).click();
    await page.getByRole('region', { name: '실패 진단' }).getByText(reason).first().waitFor({ state: 'visible' });
    assert(!await page.getByText('검토 결과를 저장했습니다.').count());
    await page.getByRole('tab', { name: '실행 이력', exact: true }).click();
    const run = page.getByRole('button', { name: /1\. 최초 요청/ });
    if (await run.getAttribute('aria-expanded') !== 'true') await run.click();
    await page.getByRole('button', { name: '하위 처리 단계 3개' }).click();
    await page.locator('button[aria-controls="step-detail-failure"]').click();
    await page.getByRole('region', { name: '실패 진단' }).getByText(reason).first().waitFor({ state: 'visible' });
    await page.reload();
    await page.getByRole('region', { name: '실패 진단' }).getByText(reason).first().waitFor({ state: 'visible' });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
    assert.deepEqual(errors, []);
    await page.close();
  }
  console.log('failure diagnosis conversation/document/history/reload desktop/mobile: passed');
} finally {
  await browser.close();
}
