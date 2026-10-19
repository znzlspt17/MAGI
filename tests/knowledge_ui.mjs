// 실제 브라우저에서 로컬 테스트 API를 통해 화면 동작을 확인한다.
import {createRequire} from 'node:module';
import {join} from 'node:path';
import assert from 'node:assert/strict';
const require = createRequire(join(process.argv[2], 'package.json'));
const {chromium} = require('playwright');
let browser;
try { browser = await chromium.launch({headless: true}); }
catch (error) {
    if (!error.message.includes("Executable doesn't exist")) throw error;
    browser = await chromium.launch({headless: true, channel: 'msedge'});
}
try {
    const page = await browser.newPage({viewport: {width: 1440, height: 900}});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.goto(process.argv[3]);
    await page.getByRole('button', {name:'지식 검색',exact:true}).click();
    await page.waitForFunction(() => document.querySelector('#knowledge-session').options.length === 3);
    assert.equal(await page.locator('#project-create').count(),0);
    const sessionLabels = await page.locator('#knowledge-session option').allTextContents();
    assert.equal(new Set(sessionLabels).size,3);
    await page.locator('#knowledge-session').selectOption('a'.repeat(32));
    await page.waitForFunction(() => document.querySelector('#knowledge-graph').dataset.settled === 'true');
    const state = () => page.evaluate(() => { const cy = document.querySelector('#knowledge-graph')._cyreg.cy; return {pan:cy.pan(), zoom:cy.zoom(), positions:cy.nodes().map(n => ({id:n.id(),...n.position()})), count:cy.nodes().length}; });
    assert.equal(await page.locator('#graph-inspector').isVisible(),false);
    assert.equal(await page.locator('#knowledge-list').isVisible(),false);
    const box = await page.locator('#knowledge-graph').boundingBox();
    assert.ok(box.width > 1000 && box.height > 800, JSON.stringify(box));
    assert.ok(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight));
    await page.screenshot({path:process.argv[4]});
    await page.locator('#graph-list-toggle').click();
    await page.locator('#knowledge-nodes button').last().click();
    const selected = await state();
    await page.locator('#knowledge-detail summary').click();
    await page.getByRole('button',{name:'다음 내용 읽기',exact:true}).click();
    await page.waitForFunction(() => document.querySelector('#knowledge-detail details pre').textContent.endsWith('END'));
    assert.equal(await page.locator('#knowledge-detail details pre').evaluate(el => (el.textContent.match(/😀/gu)||[]).length),12010);
    await page.getByRole('button',{name:'주변 관계 펼치기',exact:true}).click();
    await page.waitForFunction(() => document.querySelector('#knowledge-graph').dataset.settled === 'true');
    assert.deepEqual(await state(),selected);
    await page.locator('#graph-list-close').click();
    await page.locator('#graph-detail-close').click();
    const camera = await state();
    const point = await page.evaluate(() => document.querySelector('#knowledge-graph')._cyreg.cy.nodes()[0].renderedPosition());
    await page.mouse.click(box.x+point.x,box.y+point.y);
    await page.locator('#graph-inspector').waitFor();
    assert.deepEqual((await state()).pan,camera.pan);
    assert.equal((await state()).zoom,camera.zoom);
    await page.locator('#graph-detail-close').click();
    await page.mouse.move(box.x+point.x,box.y+point.y); await page.mouse.down();
    await page.mouse.move(box.x+point.x+60,box.y+point.y+30,{steps:12}); await page.mouse.up();
    await page.waitForFunction(() => document.querySelector('#knowledge-graph').dataset.settled === 'true');
    assert.notDeepEqual((await state()).positions,camera.positions);
    await page.locator('#knowledge-query').fill('오프라인'); await page.locator('#knowledge-form').press('Enter');
    await page.getByText('검색된 청크 인용문',{exact:true}).waitFor();
    assert.equal(await page.evaluate(() => document.querySelector('#knowledge-graph')._cyreg.cy.$('node.match').length),1);
    await page.locator('#graph-list-close').click();
    // 실제 저장 데이터와 구별되는, 100개 항목·320개 관계의 합성 응답.
    const nodes = Array.from({length:100},(_,i) => ({id:'g'+i,kind:i<34?['input','decision','requirement','review'][i%4]:'spec',body:'긴 한국어 지식 제목 '+i+' 테스트',job_id:'job',active:true,attrs:{artifact_hash:'version-1',artifact_path:'spec.md',section:'architecture',requirement_id:i%4===2?'REQ-'+i:undefined}}));
    const edges = Array.from({length:320},(_,i)=>({id:'ge'+i,source:'g'+(i%34),target:'g'+(34+i%66),kind:'derived'}));
    await page.route('**/api/knowledge/graph?*',r=>r.fulfill({json:{nodes,edges,has_more:true}}));
    await page.locator('#knowledge-query').fill(''); await page.locator('#knowledge-form').press('Enter');
    await page.waitForFunction(() => document.querySelector('#knowledge-graph')._cyreg.cy.nodes().length===35);
    await page.waitForFunction(() => document.querySelector('#knowledge-graph').dataset.settled === 'true');
    // 빈 세션과 연결 없는 항목도 다른 상태로 표시한다.
    await page.route('**/api/knowledge/graph?*', async r => {
        const job = new URL(r.request().url()).searchParams.get('job_id');
        if (job === 'empty') await new Promise(resolve => setTimeout(resolve,150));
        return r.fulfill({json: job === 'empty' ? {nodes:[],edges:[],has_more:false} : job === 'orphan' ? {nodes:[{id:'alone',kind:'decision',body:'단독 항목',job_id:'orphan',active:true,attrs:{}}],edges:[],has_more:false} : {nodes,edges,has_more:true}});
    });
    await page.locator('#knowledge-session').evaluate(select => {
        for (const id of ['empty','orphan']) { const option = document.createElement('option'); option.value=id; option.textContent=id; select.append(option); }
    });
    await page.locator('#knowledge-session').selectOption('empty');
    await page.getByText('아직 저장된 지식이 없습니다.',{exact:true}).waitFor();
    await page.locator('#knowledge-session').selectOption('orphan');
    await page.waitForFunction(() => document.querySelector('#knowledge-graph')._cyreg.cy.nodes().length===1);
    assert.ok((await page.locator('#knowledge-notice').textContent()).includes('현재 범위에 관계 없음'));
    const slow = page.waitForRequest(r => r.url().includes('job_id=empty'));
    await page.locator('#knowledge-session').selectOption('empty'); await slow;
    await page.locator('#knowledge-session').selectOption('orphan');
    await page.waitForResponse(r => r.url().includes('job_id=empty'));
    await page.waitForFunction(() => document.querySelector('#knowledge-graph')._cyreg.cy.nodes().length===1);
    await page.locator('#knowledge-session').selectOption('a'.repeat(32));
    await page.waitForFunction(() => document.querySelector('#knowledge-graph')._cyreg.cy.nodes().length===35);
    await page.waitForFunction(() => document.querySelector('#knowledge-graph').dataset.settled==='true');
    const validateLabels = async () => {
        const rects = await page.locator('.graph-node-label').evaluateAll(els=>els.map(e=>{ const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};}));
        assert.ok(rects.length<=8);
        for(let i=0;i<rects.length;i++) for(let j=i+1;j<rects.length;j++) {const a=rects[i],b=rects[j]; assert.ok(!(a.x<b.x+b.w&&a.x+a.w>b.x&&a.y<b.y+b.h&&a.y+a.h>b.y));}
    };
    await validateLabels(); await page.screenshot({path:process.argv[4].replace('.png','-summary.png')});
    // 드래그 중 프레임 간격 측정: 별도 모델 호출이나 DB 쓰기 없음.
    const pos = await page.evaluate(() => document.querySelector('#knowledge-graph')._cyreg.cy.nodes()[0].renderedPosition());
    const frames = page.evaluate(() => new Promise(resolve=>{const deltas=[];let previous=performance.now(),start=previous;function tick(now){deltas.push(now-previous);previous=now;if(now-start<1600)requestAnimationFrame(tick);else resolve(deltas.slice(1).sort((a,b)=>a-b)[Math.floor((deltas.length-1)*.95)]);}requestAnimationFrame(tick);}));
    await page.mouse.move(box.x+pos.x,box.y+pos.y); await page.mouse.down(); await page.mouse.move(box.x+pos.x+85,box.y+pos.y+45,{steps:25});await page.mouse.up();
    const p95 = await frames; assert.ok(p95<=33, 'p95='+p95);
    await page.waitForFunction(() => document.querySelector('#knowledge-graph').dataset.settled === 'true');
    await page.locator('#graph-detail-mode').click();
    await page.waitForFunction(() => document.querySelector('#knowledge-graph')._cyreg.cy.nodes().length===100);
    await page.waitForFunction(() => document.querySelector('#knowledge-graph').dataset.settled === 'true');
    const detailPoint = await page.evaluate(() => document.querySelector('#knowledge-graph')._cyreg.cy.nodes()[0].renderedPosition());
    const detailFrames = page.evaluate(() => new Promise(resolve=>{const values=[];let prev=performance.now(),start=prev;function tick(now){values.push(now-prev);prev=now;if(now-start<1600)requestAnimationFrame(tick);else resolve(values.slice(1).sort((a,b)=>a-b)[Math.floor((values.length-1)*.95)]);}requestAnimationFrame(tick);}));
    await page.mouse.move(box.x+detailPoint.x,box.y+detailPoint.y);await page.mouse.down();await page.mouse.move(box.x+detailPoint.x+50,box.y+detailPoint.y+30,{steps:25});await page.mouse.up();
    const detailP95=await detailFrames;assert.ok(detailP95<=33,'100 nodes p95='+detailP95);
    await page.waitForFunction(() => document.querySelector('#knowledge-graph').dataset.settled === 'true');
    await page.setViewportSize({width:2560,height:1440}); await page.locator('#graph-fit').click();
    await validateLabels(); await page.screenshot({path:process.argv[4].replace('.png','-2560.png')});
    await page.getByText('설정',{exact:true}).click();await page.locator('#graph-pause').check();
    const paused=await state();await page.locator('#graph-zoom-in').click();assert.deepEqual((await state()).positions,paused.positions);
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:process.argv[5]});
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({desktop:'1440x900,2560x1440',synthetic_nodes:100,synthetic_edges:320,summary_p95_ms:p95,detail_100_p95_ms:detailP95}));
} finally { await browser.close(); }
