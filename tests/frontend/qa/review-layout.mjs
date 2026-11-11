import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const require = createRequire(new URL('../../../frontend/package.json', import.meta.url));
const {chromium} = require('playwright');
const output = fileURLToPath(new URL('../../../.cache/astryx-layout/', import.meta.url));
await mkdir(output, {recursive:true});
const browser = await chromium.launch({headless:true, channel:'msedge'});
const results = [], failures = [];
const base = process.env.QA_BASE_URL || 'http://127.0.0.1:5173';
const path = '/jobs/' + 'a'.repeat(32) + '?role=user&status=PASS_PENDING_USER_APPROVAL';
const cases = [
  ...[1920,2560].map(width=>({name:`review-${width}`,width,query:''})),
  ...[390,1440,1919,1920,2240,2560].map(width=>({name:`long-${width}`,width,query:'&qa=layout-long',long:true})),
  {name:'zoom-equivalent-200',width:960,height:540,scale:2,query:'&qa=layout-long',long:true},
  ...['approved','unknown'].flatMap(state=>[1920,2560].map(width=>({name:`${state}-${width}`,width,query:`&review_state=${state}`}))),
  ...['error','loading','empty'].flatMap(state=>[1920,2560].map(width=>({name:`${state}-${width}`,width,state,query:`&qa=${state}&target=requirement-review`}))),
  ...['limited','unavailable'].flatMap(state=>[1920,2560].map(width=>({name:`${state}-${width}`,width,state,query:`&review_kind=${state}`}))),
];
function check(name, action) { try { action(); } catch (error) { failures.push({name,message:error.message}); } }
try {
  for (const config of cases) {
    const {width,name}=config;
    const page = await browser.newPage({viewport:{width,height:config.height || 1080},deviceScaleFactor:config.scale || 1,reducedMotion:'reduce'});
    const errors=[]; page.on('pageerror', error => errors.push(error.message));
    await page.goto(base + path + config.query, {waitUntil:'networkidle'});
    if(width<1920) await page.getByRole('button',{name:'대화와 검토 열기',exact:true}).click();
    const compact=page.locator('.rr-compact');
    if(config.state==='loading') await compact.getByRole('status',{name:'요구사항 근거 조회 중'}).waitFor();
    else if(config.state==='error') await compact.getByRole('button',{name:'근거표 다시 조회'}).waitFor();
    else if(config.state==='unavailable') await compact.getByText('검토 근거 준비 전',{exact:true}).waitFor();
    else await compact.locator('.rr-review-status').waitFor();
    if(config.long) {
      // 긴 번역 문구가 들어와도 버튼의 레이블이 잘리지 않는지 같은 DOM 구조로 검사한다.
      await compact.getByRole('button',{name:'전체 근거 보기',exact:true}).evaluate(button=>{
        const walker=document.createTreeWalker(button,NodeFilter.SHOW_TEXT);let node;
        while((node=walker.nextNode())) if(node.textContent.trim()==='전체 근거 보기') {node.textContent='전체 근거 보기: 아주 긴 한국어 버튼 문구와 LONG_IDENTIFIER_WITHOUT_SPACES_'.repeat(3);break;}
      });
    }
    const metrics = await page.evaluate(() => {
      const rect = selector => document.querySelector(selector).getBoundingClientRect().toJSON();
      const clipped=[];
      const walker=document.createTreeWalker(document.querySelector('.workspace-conversation'),NodeFilter.SHOW_TEXT);
      let textNode;
      while((textNode=walker.nextNode())) {
        const element=textNode.parentElement;
        if (!textNode.textContent.trim() || !element.checkVisibility() || element.closest('[role="status"],.sr-only')) continue;
        const elementBox=element.getBoundingClientRect();
        // 화면읽기 전용 레이블은 의도적으로 1px 영역 안에 숨긴다.
        if(elementBox.width<=1 && elementBox.height<=1) continue;
        const range=document.createRange();range.selectNodeContents(textNode);
        const bounds=range.getBoundingClientRect();
        let checkX=true,checkY=true;
        for(let ancestor=element;ancestor && ancestor.closest('.workspace-conversation');ancestor=ancestor.parentElement) {
          const style=getComputedStyle(ancestor),box=ancestor.getBoundingClientRect();
          // 스크롤로 접근할 수 있는 내용은 고정 높이에 잘린 텍스트와 구분한다.
          if(['auto','scroll'].includes(style.overflowX)) checkX=false;
          if(['auto','scroll'].includes(style.overflowY)) checkY=false;
          if(checkX && ['hidden','clip'].includes(style.overflowX) && (bounds.left<box.left-1 || bounds.right>box.right+1) || checkY && ['hidden','clip'].includes(style.overflowY) && (bounds.top<box.top-1 || bounds.bottom>box.bottom+1)) {
            clipped.push({text:textNode.textContent.trim(),tag:element.tagName});break;
          }
        }
      }
      return {viewport:innerWidth,scroll:document.documentElement.scrollWidth,
        layout:rect('.document-action-layout'),document:rect('.document-panel'),
        markdown:rect('.document-panel .markdown-view'),documentStyle:{paddingLeft:parseFloat(getComputedStyle(document.querySelector('.document-panel')).paddingLeft),paddingRight:parseFloat(getComputedStyle(document.querySelector('.document-panel')).paddingRight),borderLeft:parseFloat(getComputedStyle(document.querySelector('.document-panel')).borderLeftWidth),borderRight:parseFloat(getComputedStyle(document.querySelector('.document-panel')).borderRightWidth)},
        panel:rect('.workspace-conversation'),headerDirection:getComputedStyle(document.querySelector('.rr-compact .rr-header')).flexDirection,clipped,
        proseWidths:[...document.querySelectorAll('.document-panel .markdown-view p,.document-panel .markdown-view ul,.document-panel .markdown-view blockquote')].map(e=>e.getBoundingClientRect().width),
        wideBlocks:[...document.querySelectorAll('.document-panel .markdown-view pre,.document-panel .markdown-view table')].map(e=>({width:e.getBoundingClientRect().width,scroll:e.scrollWidth,client:e.clientWidth,overflow:getComputedStyle(e).overflowX})),
      };
    });
    if(width>=1920) {
      const target=Math.min(520,Math.max(440,width*.125+200));
      check(`${name}: panel width`,()=>assert.ok(Math.abs(metrics.panel.width-target)<=1,`expected ${target}, got ${metrics.panel.width}`));
      check(`${name}: document fills column`,()=>assert.ok(Math.abs(metrics.document.width-metrics.layout.width)<=1,`card ${metrics.document.width}, column ${metrics.layout.width}`));
      check(`${name}: gap`,()=>assert.ok(Math.abs(metrics.panel.left-metrics.document.right-24)<=1,`gap ${metrics.panel.left-metrics.document.right}`));
      check(`${name}: reading width`,()=>assert.ok(metrics.proseWidths.every(value=>value<=1121)));
      const innerWidth=metrics.document.width-metrics.documentStyle.paddingLeft-metrics.documentStyle.paddingRight-metrics.documentStyle.borderLeft-metrics.documentStyle.borderRight;
      check(`${name}: markdown fills card`,()=>assert.ok(Math.abs(metrics.markdown.width-innerWidth)<=1,`markdown ${metrics.markdown.width}, inner card ${innerWidth}`));
      check(`${name}: markdown left aligned`,()=>assert.ok(Math.abs(metrics.markdown.left-metrics.document.left-metrics.documentStyle.paddingLeft-metrics.documentStyle.borderLeft)<=1));
    }
    check(`${name}: compact header stacks`,()=>assert.equal(metrics.headerDirection,'column'));
    check(`${name}: text visible`,()=>assert.deepEqual(metrics.clipped,[]));
    check(`${name}: page fits`,()=>assert.ok(metrics.scroll<=width+1));
    check(`${name}: runtime`,()=>assert.deepEqual(errors,[]));
    check(`${name}: wide content scrolls internally`,()=>assert.ok(metrics.wideBlocks.every(block=>block.scroll<=block.client+1 || ['auto','scroll'].includes(block.overflow))));
    await page.screenshot({path:`${output}/${name}.png`,fullPage:true});
    if(width<1920) {
      await page.locator('.workspace-conversation button').first().press('Tab');
      await page.keyboard.press('Escape');
      await page.locator('.workspace-conversation').waitFor({state:'hidden'});
      const restored=await page.getByRole('button',{name:'대화와 검토 열기',exact:true}).evaluate(e=>e===document.activeElement);
      check(`${name}: focus restored`,()=>assert.equal(restored,true));
    }
    results.push({name,width,...metrics,errors});console.log(`${name}: inspected`);await page.close();
  }
} finally {
  await browser.close();
  await writeFile(`${output}/review-layout.json`,JSON.stringify({results,failures},null,2));
}
console.log(JSON.stringify({results,failures},null,2));
if(failures.length) process.exitCode=1;
