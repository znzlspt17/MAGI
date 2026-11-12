import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
const require=createRequire(new URL('../../../frontend/package.json',import.meta.url));
const {chromium}=require('playwright');
const output=new URL('../../../.cache/composer-alignment/',import.meta.url);
await mkdir(output,{recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true});
const results=[],failures=[];
try {
 for(const [view,width] of [['new',390],['new',768],['new',1440],['document',390],['document',1920]]) {
  const page=await browser.newPage({viewport:{width,height:width===390?844:1080},reducedMotion:'reduce'});
  await page.goto(view === "new" ? "http://127.0.0.1:5173/?role=admin" : "http://127.0.0.1:5173/jobs/" + "a".repeat(32) + "?role=admin&status=PASS_PENDING_USER_APPROVAL", {waitUntil:"domcontentloaded"});
  if(view==='document' && width<1920) await page.getByRole('button',{name:'대화와 검토 열기',exact:true}).click();
  await page.locator('.chat-prompt textarea').waitFor();
  await page.evaluate(()=>document.fonts.ready);
  const area=page.locator('.chat-prompt textarea');
  await area.fill('준비');
  for(const [state,value] of [['empty',''],['single','한 줄 작성 내용입니다'],['multi','첫 번째 줄\n두 번째 줄\n세 번째 줄'],['maximum',Array.from({length:9},(_,i)=>`${i}번째 줄`).join('\n')]]) {
   await area.fill(value);
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   const data=await page.locator('.chat-prompt').evaluate(group=>{
    const textarea=group.querySelector('textarea'), expand=group.querySelector('.expand-input'), send=group.querySelector('.chat-prompt-footer button');
    const shape=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom,right:r.right,center:r.y+r.height/2,padding:s.padding,lineHeight:s.lineHeight,display:s.display,position:s.position}};
    const t=shape(textarea), e=shape(expand), b=shape(send), es=shape(expand.querySelector('svg')), bs=shape(send.querySelector('svg'));
    const path=send.querySelector('svg path'), box=path.getBBox(), matrix=path.getScreenCTM();
    const a=new DOMPoint(box.x,box.y).matrixTransform(matrix), z=new DOMPoint(box.x+box.width,box.y+box.height).matrixTransform(matrix);
    const glyph={x:a.x,y:a.y,width:z.x-a.x,height:z.y-a.y,deltaX:(a.x+z.x)/2-(b.x+b.width/2),deltaY:(a.y+z.y)/2-b.center};
    const st=getComputedStyle(textarea), lineCenter=t.y+parseFloat(st.borderTopWidth)+parseFloat(st.paddingTop)+parseFloat(st.lineHeight)/2;
    return {textarea:t,expand:e,send:b,expandSvg:es,sendSvg:bs,glyph,disabled:send.disabled,lineCenter,deltaExpand:e.center-b.center,deltaLine:lineCenter-b.center,deltaSvg:es.center-bs.center,overlap:t.right>e.x && t.y<e.bottom && t.bottom>e.y, textRight:t.right-parseFloat(st.paddingRight)};
   });
   results.push({view,width,state,...data});
   const check=(name,fn)=>{try{fn()}catch(e){failures.push(`${view} ${width} ${state} ${name}: ${e.message}`)}};
   check('button centers',()=>assert.ok(Math.abs(data.deltaExpand)<=1,JSON.stringify(data)));
   check('svg centers',()=>assert.ok(Math.abs(data.deltaSvg)<=1,JSON.stringify(data)));
   check('expand icon dimensions',()=>assert.ok(Math.abs(data.expandSvg.width-17)<=0.5 && Math.abs(data.expandSvg.height-17)<=0.5,JSON.stringify(data)));
   check('send glyph center',()=>assert.ok(Math.abs(data.glyph.deltaX)<=1 && Math.abs(data.glyph.deltaY)<=1,JSON.stringify(data)));
   check('send glyph dimensions',()=>assert.ok(data.glyph.width>=14 && data.glyph.height>=18,JSON.stringify(data)));
   check('send disabled state',()=>assert.equal(data.disabled,state==='empty'));
   check('touch size',()=>assert.ok(data.expand.width>=44 && data.expand.height>=44 && data.send.width>=44 && data.send.height>=44,JSON.stringify(data)));
   check('text overlap',()=>assert.ok(data.textRight<=data.expand.x+1,JSON.stringify(data)));
   if((view==='new' && state==='single') || (state==='empty' && data.textarea.height<=45))check('text center',()=>assert.ok(Math.abs(data.deltaLine)<=1,JSON.stringify(data)));
   if(state==='single'||state==='multi')await page.screenshot({path:new URL(`${process.env.QA_PHASE||'before'}-${width}-${state}.png`,output).pathname.slice(1),fullPage:true});
  }
  await page.close();
 }
} finally {await browser.close();await writeFile(new URL(`${process.env.QA_PHASE||'before'}.json`,output),JSON.stringify({results,failures},null,2));}
console.log(JSON.stringify({results,failures},null,2));
if(failures.length)process.exitCode=1;
