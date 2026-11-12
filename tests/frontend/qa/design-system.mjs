import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const require=createRequire(new URL('../../../frontend/package.json',import.meta.url));
const {chromium}=require('playwright');
const output=fileURLToPath(new URL('../../../.cache/design-system-finish/',import.meta.url));
await mkdir(output,{recursive:true});
const base=process.env.QA_BASE_URL || 'http://127.0.0.1:5173';
const browser=await chromium.launch({channel:'msedge',headless:true});
const results=[],failures=[];
function check(name,fn){try{fn();}catch(error){failures.push({name,message:error.message});}}
async function inspect(page,name,width){
 const data=await page.evaluate(()=>{
  const shape=el=>{if(!el)return null;const s=getComputedStyle(el);return{...el.getBoundingClientRect().toJSON(),radius:s.borderRadius,background:s.backgroundColor,padding:s.padding};};
  const panel=document.querySelector('.workspace-content');
  const tabs=document.querySelector('[role=tablist][aria-label="작업 보기"]');
  const composer=document.querySelector('.chat-prompt');
  const area=composer?.querySelector('textarea');
  const borders=[];
  for(let el=area;el;el=el.parentElement){const s=getComputedStyle(el);if(parseFloat(s.borderTopWidth)>0 && s.borderTopStyle!=='none' && s.borderTopColor!=='rgba(0, 0, 0, 0)')borders.push({tag:el.tagName,class:el.className});if(el===composer)break;}
  const menu=[...document.querySelectorAll('[role=menu]')].find(element=>element.checkVisibility());
  const approval=[...document.querySelectorAll('.workspace-conversation button')].find(element=>element.textContent.trim()==='이 명세 승인');
  const retry=[...document.querySelectorAll('.agent-composer button')].find(element=>element.textContent.trim()==='저장된 결과로 추가 실행');
  let approvalViewport=document.querySelector('.workspace-conversation');
  for(let element=approval?.parentElement;element && element!==approvalViewport;element=element.parentElement){const style=getComputedStyle(element);if(['auto','scroll'].includes(style.overflowY)){approvalViewport=element;break;}}
  return{viewport:{width:innerWidth,height:innerHeight,scroll:document.documentElement.scrollWidth},frame:shape(panel),header:shape(document.querySelector('.workspace-topbar')),sidebar:shape(document.querySelector('[data-slot=sidebar-container] [data-slot=sidebar-inner]')),tabs:shape(tabs),composer:shape(composer),retry:shape(retry),textarea:shape(area),rows:area?.rows,visibleLabels:[...(area?.labels || [])].filter(element=>element.checkVisibility() && element.getBoundingClientRect().height>1 && element.getBoundingClientRect().width>1).map(element=>element.textContent),borders,send:shape(composer?.querySelector('.chat-prompt-footer button')),approval:shape(approval),approvalViewport:shape(approvalViewport),menu:shape(menu),menuSurface:shape(menu?.closest('[popover]')),items:[...document.querySelectorAll('[role=menuitem]')].filter(e=>e.checkVisibility()).map(e=>({text:e.textContent,icons:e.querySelectorAll('svg').length,box:shape(e)}))};
 });
 check(`${name}: no page overflow`,()=>assert.ok(data.viewport.scroll<=width+1));
 check(`${name}: white work surface`,()=>assert.equal(data.frame.background,'rgb(255, 255, 255)'));
 check(`${name}: white header within frame`,()=>assert.equal(data.header.background,'rgb(255, 255, 255)'));
 check(`${name}: square frame`,()=>assert.equal(data.frame.radius,'0px'));
 check(`${name}: outer top`,()=>assert.ok(Math.abs(data.frame.top)<=1));
 check(`${name}: outer right`,()=>assert.ok(Math.abs(width-data.frame.right)<=1));
 if(width>=768){
  check(`${name}: matching frame top`,()=>assert.ok(Math.abs(data.frame.top-data.sidebar.top)<=1));
  check(`${name}: matching frame bottom`,()=>assert.ok(Math.abs(data.frame.bottom-data.sidebar.bottom)<=1));
  check(`${name}: frame gap`,()=>assert.ok(Math.abs(data.frame.left-data.sidebar.right)<=1));
 }
 if(data.tabs){check(`${name}: underline tabs only`,()=>assert.ok(data.tabs.background==='rgba(0, 0, 0, 0)' || data.tabs.background==='transparent'));}
 // 모바일 메뉴를 열면 뒤의 검토 패널은 닫힌다. 숨긴 작성창의 라벨은 검사하지 않는다.
 if(data.composer && data.composer.width>0 && data.textarea.height>0){
  check(`${name}: one composer border`,()=>assert.equal(data.borders.length,1,JSON.stringify(data.borders)));
  check(`${name}: one visible input label`,()=>assert.equal(data.visibleLabels.length,1,JSON.stringify(data.visibleLabels)));
  check(`${name}: composer radius`,()=>assert.equal(data.composer.radius,'28px'));
  check(`${name}: send aligned right`,()=>assert.ok(data.send.right>=data.composer.right-20));
  if(name.startsWith('new-'))check(`${name}: caller rows respected`,()=>assert.equal(data.rows,1));
 }
 if(data.menu){
  check(`${name}: menu width`,()=>assert.ok(Math.abs((data.menuSurface||data.menu).width-280)<=1,JSON.stringify(data.menuSurface||data.menu)));
  check(`${name}: menu icons retained`,()=>assert.ok(data.items.length>=6 && data.items.every(item=>item.icons>0)));
  check(`${name}: menu target height`,()=>assert.ok(data.items.every(item=>item.box.height>=(width<768?44:36))));
  check(`${name}: menu within viewport`,()=>assert.ok((data.menuSurface||data.menu).left>=8 && (data.menuSurface||data.menu).right<=width-8));
 }
 if(name.startsWith('review-'))check(`${name}: primary approval visible`,()=>assert.ok(data.approval && data.approval.top>=data.approvalViewport.top-1 && data.approval.bottom<=data.approvalViewport.bottom+1));
 if(name.startsWith('review-') && data.retry)check(`${name}: retry separated from composer`,()=>assert.ok(Math.abs(data.retry.top-data.composer.bottom-12)<=1,`gap ${data.retry.top-data.composer.bottom}`));
 await page.screenshot({path:`${output}/${name}.png`,fullPage:true});
 results.push({name,width,...data});console.log(`${name}: inspected`);
}
try{
 for(const width of [390,1440,1919,1920,2560]){
  const page=await browser.newPage({viewport:{width,height:width===390?844:1080},reducedMotion:'reduce'});
  for(const view of ['new','review']){
   await page.goto(base+(view==='new'?'/?role=admin':`/jobs/${'a'.repeat(32)}?role=admin&status=PASS_PENDING_USER_APPROVAL`),{waitUntil:'domcontentloaded'});
   await page.locator('.workspace-topbar h1').waitFor();
   await page.evaluate(async()=>{await document.fonts.ready; await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));});
   if(view==='review' && width<1920)await page.getByRole('button',{name:'대화와 검토 열기',exact:true}).click();
   if(view==='review'){await page.locator('.rr-compact .rr-review-status').waitFor();const stage=page.locator('.workspace-steps[role=status]'); await stage.waitFor();}
   await inspect(page,`${view}-${width}`,width);
   if(view==='new'){
    await page.locator('.chat-prompt textarea').focus();
    const focus=await page.locator('.chat-prompt').evaluate(element=>({outline:getComputedStyle(element).outlineWidth,inner:[...element.querySelectorAll('textarea,.magi-composer-control')].map(node=>({width:getComputedStyle(node).outlineWidth,style:getComputedStyle(node).outlineStyle,shadow:getComputedStyle(node).boxShadow}))}));
    // outline-style:none은 계산된 폭이 남아 있어도 외곽선을 그리지 않는다.
    check(`focus-${width}: single focus owner`,()=>assert.ok(focus.outline==='2px' && focus.inner.every(value=>(value.width==='0px' || value.style==='none') && value.shadow==='none'),JSON.stringify(focus)));
    await page.screenshot({path:`${output}/new-focused-${width}.png`,fullPage:true});
   }
  }
  if(width===390){await page.keyboard.press('Escape');await page.getByRole('button',{name:'메뉴 열기',exact:true}).click();}
  await page.getByRole('button',{name:'내 계정',exact:true}).click();
  await page.getByRole('menu').waitFor();
  await inspect(page,`account-${width}`,width);
  await page.keyboard.press('Escape');
  if(width>=768){
   const frame=page.locator('.workspace-content');
   const expandedWidth=await frame.evaluate(element=>element.getBoundingClientRect().width);
   await page.getByRole('button',{name:'메뉴 접기',exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('[data-slot="sidebar-gap"]').getBoundingClientRect().width===0);
   const visible=await page.locator('[data-slot="sidebar-container"]').isVisible();
   const inert=await page.locator('[data-slot="sidebar-container"]').getAttribute('inert');
   const collapsedWidth=await frame.evaluate(element=>element.getBoundingClientRect().width);
   check(`collapse-${width}: hidden and inert`,()=>assert.ok(!visible && inert!==null));
   check(`collapse-${width}: content expands`,()=>assert.ok(collapsedWidth>expandedWidth));
   await page.screenshot({path:`${output}/collapsed-${width}.png`,fullPage:true});
   await page.getByRole('button',{name:'메뉴 열기',exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('[data-slot="sidebar-gap"]').getBoundingClientRect().width>0);
   const expandedAgain=await page.locator('[data-slot="sidebar-container"]').isVisible();
   check(`expand-${width}: visible again`,()=>assert.equal(expandedAgain,true));
  }
  await page.close();
 }
}finally{await browser.close();await writeFile(`${output}/common-ui.json`,JSON.stringify({results,failures},null,2));}
console.log(JSON.stringify({cases:results.length,failures},null,2));
if(failures.length)process.exitCode=1;
