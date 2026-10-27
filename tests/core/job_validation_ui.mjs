import {createRequire} from 'node:module';
import {join} from 'node:path';
import {mkdirSync} from 'node:fs';
import assert from 'node:assert/strict';
const {chromium}=createRequire(join(process.argv[2],'package.json'))('playwright');
const browser=await chromium.launch({headless:true,channel:process.platform==='win32'?'msedge':undefined});
const job='a'.repeat(32),execution='c'.repeat(32);
try {
 const page=await browser.newPage({timezoneId:'UTC'}), errors=[],queries=[];
 let fail=false;
 page.on('pageerror',error=>errors.push(error.message));
 await page.addInitScript(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.__copiedDiagnostic=text;}}}));
 const old={record_id:'old',created_at:'2026-10-27T17:23:58+09:00',execution_id:null,execution_link:'unconfirmed',state:'recognized',stage:'spec_compile',error_code:'SPEC_COMPILATION_INVALID',failed_checks:['spec_blocks'],attempt:4,validation_reason:'empty_section',validation_section:'out_of_scope',validation_index:null};
 const linked={...old,record_id:'new',execution_id:execution,execution_link:'confirmed',validation_reason:'fixed_heading',validation_section:'architecture',validation_index:2};
 await page.route('**/api/**',route=>{
  const url=new URL(route.request().url()); let data={};
  if(url.pathname==='/api/auth/info')data={public:true,login_available:true};
  else if(url.pathname==='/api/me')data={id:'fixture-admin',role:'admin',csrf:'fake-fixture'};
  else if(url.pathname==='/api/admin/overview')data={users:[],executions:[]};
  else if(url.pathname==='/api/admin/cleanup/catalog')data={jobs:[{id:job,request:'진단 테스트용 작업',status:'error'}],pending:[]};
  else if(url.pathname==='/api/admin/job')data={id:job,request:'진단 테스트용 작업',status:'error',session_events:[]};
  else if(url.pathname==='/api/admin/job/validation'){
   queries.push(url.searchParams);
   if(fail)return route.fulfill({status:503,json:{error:'테스트 진단 조회 오류'}});
   const offset=Number(url.searchParams.get('offset')||0);
   data={items:offset?[{...old,record_id:'bad',state:'unreadable',validation_reason:null}]:[old,linked],offset,limit:20,next_offset:offset?null:20};
  }
  else if(url.pathname==='/api/admin/logs/status')data={state:'ready',collector_seen:true,free_bytes:1e10,warnings:[]};
  else if(url.pathname==='/api/admin/logs'){
   queries.push(url.searchParams);
   data={items:[],start:new Date(Date.now()-604799000).toISOString(),end:new Date().toISOString(),next_offset:null,storage:{state:'ready'}};
  }
  return route.fulfill({json:data});
 });
 mkdirSync('.cache/validation-preview',{recursive:true});
 for(const [name,width,height] of [['desktop',1440,900],['mobile',390,844],['low',1024,480]]){
  await page.setViewportSize({width,height}); await page.goto(process.argv[3]+'/admin/data?job_id='+job);
  await page.getByRole('tab',{name:'진단',exact:true}).click();
  await page.getByText('실행 연결 미확인',{exact:true}).waitFor();
  assert.equal(await page.getByRole('tab',{name:'진단',exact:true}).getAttribute('aria-selected'),'true');
  await page.waitForFunction(()=>!document.querySelector('.job-validation-heading button').matches(':disabled'));
  assert.match(await page.locator('.job-validation-records time').first().textContent(),/17:23 KST/);
  assert.equal(await page.locator('.job-validation-records a').first().getAttribute('href'),`/admin/logs?job_id=${job}&period=10080`);
  assert((await page.locator('.job-validation-records a').nth(1).getAttribute('href')).includes('execution_id='+execution));
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' document overflow');
  assert(await page.locator('.jobs-detail').evaluate(e=>e.scrollWidth<=e.clientWidth+1),name+' sheet overflow');
  await page.screenshot({path:`.cache/validation-preview/${name}.png`,fullPage:false});
 }
 await page.getByRole('button',{name:'진단 요약 복사'}).first().click();
 await page.getByText('진단 요약을 복사했습니다.',{exact:true}).waitFor();
 assert.equal(await page.evaluate(()=>JSON.parse(window.__copiedDiagnostic).execution_id),null);
 await page.getByRole('button',{name:'다음 진단'}).click();
 await page.getByText('저장된 진단 형식을 해석할 수 없습니다. 원문은 표시하지 않습니다.').waitFor();
 assert(queries.some(q=>q.get('offset')==='20'));
 fail=true; await page.getByRole('button',{name:'진단 다시 조회'}).click();
 await page.getByText('테스트 진단 조회 오류',{exact:true}).waitFor();
 fail=false; await page.getByRole('button',{name:'진단 다시 조회'}).click();
 await page.getByText('실행 연결 미확인',{exact:true}).waitFor();
 await page.locator('.job-validation-records a').nth(1).click();
 await page.getByRole('heading',{name:'컨테이너 로그'}).waitFor();
 await page.getByText('조건에 맞는 로그가 없습니다.',{exact:true}).waitFor();
 assert.equal(await page.getByLabel('작업 ID',{exact:true}).inputValue(),job);
 assert.equal(await page.getByLabel('실행 ID',{exact:true}).inputValue(),execution);
 assert.equal(await page.getByRole('combobox',{name:/기간/}).inputValue(),'10080');
 assert(queries.some(q=>q.get('job_id')===job&&q.get('execution_id')===execution&&q.has('start')));
 assert.deepEqual(errors,[]);
 console.log('validation desktop/mobile/low, pagination, failure recovery, copy, and log filters passed');
} finally {await browser.close();}
