import {createRequire} from 'node:module';
import {join} from 'node:path';
import {mkdirSync} from 'node:fs';
import assert from 'node:assert/strict';
const {chromium}=createRequire(join(process.argv[2],'package.json'))('playwright');
const browser=await chromium.launch({headless:true,channel:process.platform==='win32'?'msedge':undefined});
try {
 mkdirSync('.cache/agent-workflow-preview',{recursive:true});
 for(const [name,width,height] of [['desktop',1440,1000],['mobile',390,844]]) {
  const page=await browser.newPage({viewport:{width,height}}),errors=[],mutations=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.addInitScript(()=>{window.WebSocket=class {static OPEN=1;readyState=0;constructor(){setTimeout(()=>{this.readyState=1;this.onopen?.({});},0);}close(){this.readyState=3;}};});
  const id='a'.repeat(32);
  const job={id,request:'오프라인 메모 앱의 명세를 함께 작성해주세요.',status:'NEEDS_USER_INPUT',execution_id:'current',read_only:false,
   message:'보관 기간에 대한 결정이 필요합니다.',state:{status:'NEEDS_USER_INPUT',revision:1,
    blocking_questions:['[Q1] 메모를 며칠 동안 보관할까요?'],allowed_actions:['answer','message'],wait_reason:'보관 기간의 사용자 결정을 기다립니다.',
    plan:{goal:'오프라인 메모 앱의 명세 보완',action:'ask_user',reason:'저장 정책은 사용자 결정을 확인한 뒤 명세에 반영합니다.',
     tasks:[{id:'retention',title:'메모 보관 기간 확인',status:'blocked'},{id:'spec',title:'보관 정책과 검증 조건 보완',status:'pending'}]},
    task_results:[{action:'interview',revision:1,reason:'요청에 포함되지 않은 데이터 정책을 확인했습니다.'}],document_versions:[{revision:0,hash:'fixture'}]},
   session_events:[{id:'e',action:'generate',input:{request:'오프라인 메모 앱의 명세를 함께 작성해주세요.'},summary:'명세 초안을 검토한 결과 보관 정책에 대한 결정이 필요합니다.',questions:['[Q1] 메모를 며칠 동안 보관할까요?']}],execution_graph:{nodes:[]}};
  await page.route('**/api/**',route=>{
   const request=route.request(),path=new URL(request.url()).pathname;
   if(request.method()==='POST') {mutations.push({path,data:request.postDataJSON()});return route.fulfill({status:503,json:{error:'테스트용 연결 오류'}});}
   let body;
   if(path==='/api/auth/info')body={public:false};
   else if(path==='/api/me')body={id:'fixture',role:'user',csrf:'fake-csrf'};
   else if(path==='/api/service/status')body={ready:true,active_count:0,queued_count:0,max_parallel:2,own_active_count:0};
   else if(path==='/api/me/usage')body={};
   else if(path==='/api/jobs')body=[job];
   else if(path==='/api/jobs/'+id)body=job;
   else if(path.includes('/steps/'))body={result:{summary:'저장된 작업 상태'}};
   else throw new Error('Unexpected route '+path);
   return route.fulfill({json:structuredClone(body)});
  });
  await page.goto(process.argv[3]+'/jobs/'+id);
  const plan=page.getByRole('button',{name:'현재 계획 · 오프라인 메모 앱의 명세 보완'});
  await plan.focus();await plan.press('Enter');
  await page.getByText('저장 정책은 사용자 결정을 확인한 뒤 명세에 반영합니다.').waitFor({state:'visible'});
  assert(await page.getByRole('textbox',{name:'메모를 며칠 동안 보관할까요?'}).isVisible());
  await page.getByRole('button',{name:'수정 의견 또는 추가 요청',exact:true}).click();
  const input=page.getByRole('textbox',{name:'수정 의견 또는 추가 요청',exact:true});
  await input.fill('보관 기간은 30일로 정해주세요.');
  await page.getByRole('button',{name:'의견 보내기',exact:true}).click();
  await page.getByText('테스트용 연결 오류',{exact:true}).first().waitFor();
  assert.equal(await input.inputValue(),'보관 기간은 30일로 정해주세요.');
  assert.equal(mutations.length,1);assert.equal(mutations[0].path,'/api/commands');assert.equal(mutations[0].data.kind,'message');
  assert.equal(mutations[0].data.execution_id,'current');
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  const box=await input.boundingBox();assert(box&&box.y>=0&&box.y+box.height<=height);
  await page.getByRole('textbox',{name:'메모를 며칠 동안 보관할까요?'}).scrollIntoViewIfNeeded();
  await page.screenshot({path:'.cache/agent-workflow-preview/'+name+'.png',fullPage:true});
  assert.deepEqual(errors,[]);await page.close();
 }
 console.log('Agent conversation desktop/mobile, keyboard, draft retention, message API: passed');
} finally {await browser.close();}
