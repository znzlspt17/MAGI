import {createRequire} from 'node:module';
import {join} from 'node:path';
import assert from 'node:assert/strict';
const require = createRequire(join(process.argv[2], 'package.json'));
const {chromium} = require('playwright');
const browser = await chromium.launch({headless: true, channel: 'msedge'});
try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1050}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(process.argv[3]);
    await page.locator('#job-list button').click();
    await page.getByRole('button', {name: '이어서 요청하기', exact: true}).waitFor();
    // 긴 요청 제목에서도 상태 요약의 네 항목이 카드 안에 표시되어야 한다.
    for (const width of [1920, 1440, 1200, 768, 390]) {
        await page.setViewportSize({width, height: 1050});
        await page.locator('#workspace-title').evaluate(node => {
            node.textContent = '2D 스프라이트 게임을 만들고 싶어 (ex 록맨, 건볼트, 마이티넘버나인...) AI Agent가 자동으로 만들 수 있도록 명세서를 만들어.';
        });
        const summary = await page.locator('#status-summary').evaluate(node => {
            const card = node.getBoundingClientRect();
            return {overflow: node.scrollWidth > node.clientWidth,
                inside: [...node.children].every(child => {
                    const bounds = child.getBoundingClientRect();
                    return bounds.left >= card.left && bounds.right <= card.right;
                })};
        });
        assert.equal(summary.overflow, false, `${width}px 상태 요약이 잘리면 안 됩니다.`);
        assert.equal(summary.inside, true, `${width}px 모든 상태 항목이 카드 안에 있어야 합니다.`);
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    }
    await page.setViewportSize({width: 1440, height: 1050});
    await page.locator('#job-actions textarea').fill('대시 동작을 더 자세하게 작성해주세요.');
    await page.locator('#new-job').click();
    assert.equal(await page.locator('#request-text').inputValue(), '');
    await page.locator('#job-list button').click();
    assert.equal(await page.locator('#job-actions textarea').inputValue(), '대시 동작을 더 자세하게 작성해주세요.');
    const [continued] = await Promise.all([
        page.waitForRequest(request => request.url().endsWith('/api/jobs/' + 'a'.repeat(32) + '/continue')),
        page.getByRole('button', {name: '이어서 요청하기', exact: true}).click()
    ]);
    assert.equal(continued.postDataJSON().execution_id, 'e'.repeat(32));
    await page.waitForFunction(() => document.querySelectorAll('.session-turn').length === 2);
    assert.equal(await page.locator('#job-actions textarea').inputValue(), '');
    assert.equal(await page.locator('#job-list button').count(), 1);
    await page.screenshot({path: '.pytest_cache/workspace-session.png', fullPage: true});
    await page.locator('button[data-worktab=document]').click();
    await page.locator('.markdown-view h2').first().waitFor();
    assert.equal(await page.locator('#detail-tab-document').getAttribute('aria-selected'), 'true');
    await page.locator('button[data-worktab=document]').click();
    await page.locator('.markdown-view h2').first().waitFor();
    assert.equal(await page.locator('.execution-panel').isVisible(), false);
    assert.equal(await page.locator('.document-toc').count(), 1);
    await page.screenshot({path: '.pytest_cache/workspace-document.png', fullPage: true});
    await page.locator('button[data-worktab=history]').click();
    await page.locator('.execution-panel').waitFor();
    await page.waitForResponse(response => response.url().endsWith('/api/jobs/' + 'a'.repeat(32)));
    assert.equal(await page.locator('button[data-worktab=history]').getAttribute('aria-pressed'), 'true');
    await page.locator('#detail-tab-result').click();
    await page.locator('.question-row > .question-hint').waitFor();
    for (const width of [1440, 390]) {
        await page.setViewportSize({width, height: 1050});
        const bounds = await page.locator('.question-row').first().evaluate(row => {
            const body = row.querySelector('.question-body').getBoundingClientRect();
            const context = row.querySelector(':scope > .question-hint').getBoundingClientRect();
            return {bodyX: body.x, bodyWidth: body.width, contextX: context.x, contextWidth: context.width};
        });
        assert.ok(Math.abs(bounds.bodyX - bounds.contextX) < 1, '검토 설명은 질문 본문과 정렬되어야 합니다.');
        assert.ok(Math.abs(bounds.bodyWidth - bounds.contextWidth) < 1, '검토 설명은 본문 너비를 사용해야 합니다.');
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
        await page.screenshot({path: `.pytest_cache/workspace-review-${width}.png`, fullPage: true});
    }
    await page.setViewportSize({width: 1440, height: 1050});
    assert.equal(await page.locator('button[data-surface=management]').count(),0);
    assert.equal(await page.locator('#cleanup-dialog').count(),0);
    assert.deepEqual(errors, []);
} finally { await browser.close(); }
