import {createRequire} from 'node:module';
import {join} from 'node:path';
import {mkdirSync} from 'node:fs';
import assert from 'node:assert/strict';
const {chromium}=createRequire(join(process.argv[2],'package.json'))('playwright');
const browser=await chromium.launch({headless:true,channel:process.platform==='win32'?'msedge':undefined});
try {
 const page=await browser.newPage({timezoneId:'UTC'}), errors=[], calls=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/**',route=>{
  const url=new URL(route.request().url()); let data={};
  if(url.pathname==='/api/auth/info')data={public:true,login_available:true};
  else if(url.pathname==='/api/me')data={id:'fixture-admin',role:'admin',csrf:'fake-fixture'};
  else if(url.pathname==='/api/admin/overview')data={users:[],running:[]};
  else if(url.pathname==='/api/admin/logs/status')data={state:'ready',collector_seen:true,free_bytes:10000000000,warnings:[]};
  else if(url.pathname==='/api/admin/logs'){
   calls.push(url.searchParams);
   data={start:'2026-10-26T23:45:00Z',end:'2026-10-27T00:00:00Z',next_offset:url.searchParams.has('offset')?null:200,storage:{state:'ready'},items:[{timestamp:'2026-10-27T09:00:00.775163462+09:00',service:'backend',level:'error',event:'fixture',message:'검증 오류 <script>plain-text</script> '+ '긴메시지'.repeat(120),fields:{trace_id:'a'.repeat(24)}}]};
  }
  return route.fulfill({json:data});
 });
 mkdirSync('.cache/logs-preview',{recursive:true});
 for(const [name,width,height] of [['desktop',1440,900],['mobile',390,844],['low',1024,480]]){
  await page.setViewportSize({width,height}); await page.goto(process.argv[3]+'/admin/logs');
  await page.getByRole('heading',{name:'컨테이너 로그'}).waitFor();
  await page.locator('.logs-row').first().waitFor();
  assert.match(await page.locator('.logs-row time').first().textContent(),/오전 9:00:00 KST/);
  await page.getByRole('checkbox').uncheck();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' horizontal overflow');
  await page.locator('.logs-row summary').first().click();
  await page.getByRole('button',{name:'로그 복사'}).waitFor();
  assert.equal(await page.locator('.logs-detail script').count(),0);
  assert.match(await page.locator('.logs-detail pre').first().textContent(),/2026-10-27T09:00:00\.775163462\+09:00/);
  await page.screenshot({path:`.cache/logs-preview/${name}.png`,fullPage:true});
 }
 await page.getByRole('button',{name:'이전 로그 더 보기'}).click();
 await page.waitForFunction(()=>document.querySelectorAll('.logs-row').length===2);
 assert(calls.some(p=>p.get('offset')==='200'&&p.get('end')==='2026-10-27T00:00:00Z'));
 assert.deepEqual(errors,[]);
 console.log('admin logs desktop/mobile/low viewport and pagination passed');
} finally {await browser.close();}
