// 상태가 실제 사용자 행동에 따라 바뀌는 API 모형으로 전체 인수 경로를 검증한다.
import {createRequire} from 'node:module';
import {join} from 'node:path';
import {readFileSync,mkdirSync} from 'node:fs';
import assert from 'node:assert/strict';
const {chromium}=createRequire(join(process.argv[2],'package.json'))('playwright');
const browser=await chromium.launch({headless:true,channel:process.platform==='win32'?'msedge':undefined});
try{
 mkdirSync('.cache/ai-chat-preview',{recursive:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],calls=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{
  window.__sockets=[];
  window.WebSocket=class{
   static OPEN=1;static CLOSED=3;readyState=0;
   constructor(){window.__sockets.push(this);setTimeout(()=>{if(this.readyState===3)return;this.readyState=1;this.onopen?.({});},0);}
   close(){if(this.readyState===3)return;this.readyState=3;this.onclose?.({});}
   send(){}
   emit(value){this.onmessage?.({data:JSON.stringify(value)});}
  };
 });
 let current=null,expired=false,status={busy:false};
 const id='a'.repeat(32),english={content:'# English specification\n\nStore notes for 30 days.',filename:'spec.en.md',source_hash:'fixture'},korean={content:'# 한국어 명세\n\n메모를 30일 동안 보관합니다.',filename:'spec.ko.md',source_hash:'fixture',language:'ko'};
 const forms={A:{question_id:'A',question:'보관 기간',input_type:'text',options:[],form_version:'A-v1'},B:{question_id:'B',question:'저장 방식',input_type:'text',options:[],form_version:'B-v1'}};
 const node={id:'current',stage:'await_user',status:'waiting',detail_available:true};
 await page.route('**/api/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname,data=req.postDataJSON();calls.push({path,data,headers:req.headers()});
  let body={};
  if(path==='/api/auth/info')body={public:true,login_available:true};
  else if(expired)return route.fulfill({status:401,json:{error:'세션이 만료되었습니다.'}});
  else if(path==='/api/me')body={id:'owner',role:'user',csrf:'fixture-csrf'};
  else if(path==='/api/me/usage')body={runs:0,remaining_runs:3};
  else if(path==='/api/service/status')body=status;
  else if(path==='/api/jobs'&&req.method()==='GET')body=current?[current]:[];
  else if(path==='/api/commands'&&data.kind==='generate'){
   assert.equal(data.input,'오프라인 메모 앱을 만들어주세요.');
   current={id,request:data.input,status:'NEEDS_USER_INPUT',execution_id:'execution-1',state:{candidate_hash:'f'.repeat(64),status:'NEEDS_USER_INPUT',question_forms:forms,blocking_questions:['[A] 보관 기간','[B] 저장 방식'],saved_answers:[]},session_events:[{id:'event-generate',action:'generate',input:{request:data.input},status:'NEEDS_USER_INPUT',summary:'메모 앱을 만들기 위해 두 가지를 확인합니다.',questions:['[A] 보관 기간','[B] 저장 방식'],started_at:'2026-10-21T00:00:00Z'}],execution_graph:{nodes:[node]}};
   status={phase:'waiting',busy:true,mine:true,deadline:Date.now()/1000+120};body=current;
  }else if(path==='/api/commands'&&data.kind==='answer'){
   assert.equal(data.execution_id,'execution-1');
   const answers=data.input;current.state.saved_answers.push(...answers);
   current.state.blocking_questions=current.state.blocking_questions.filter(raw=>!answers.some(answer=>raw.startsWith('['+answer.question_id+']')));
   if(!current.state.blocking_questions.length){current.status='PASS_PENDING_USER_APPROVAL';current.state.status=current.status;current.execution_graph.nodes=[{...node,stage:'compose_candidate',status:'waiting_approval',has_document:true}];}
   current.session_events.push({id:'event-answer-'+current.state.saved_answers.length,action:'answer',input:{answers},summary:current.state.blocking_questions.length?'답변을 저장했습니다. 남은 질문을 확인해주세요.':'명세 검토본이 준비되었습니다.',questions:current.state.blocking_questions,document_step_id:current.state.blocking_questions.length?undefined:'current'});
   body=current;
  }else if(path==='/api/commands'&&data.kind==='approve'){
   assert.equal(data.execution_id,'execution-1');assert.equal(data.candidate_hash,'f'.repeat(64));current.status='FINALIZED';current.state.status='FINALIZED';current.can_continue=true;current.latest_completed={step_id:'current'};current.execution_graph.nodes=[{...node,stage:'approve',status:'completed',has_document:true}];current.session_events.push({id:'event-approve',action:'approve',summary:'최종 명세가 승인되었습니다.',document_step_id:'current'});body=current;
  }else if (path.endsWith('/requirement-review')) body = { status: 'unavailable', message: '예시 근거 자료 없음' };
    else if(path.endsWith('/document'))body=korean;
  else if(path.includes('/steps/'))body={result:{summary:'요구사항 확인'},...(current.status==='NEEDS_USER_INPUT'?{}:{document:english})};
  else if(path==='/api/jobs/'+id)body=current;
  else if(path==='/api/lease/release'){status={busy:false};body={ok:true};}
  else if(path==='/api/lease/resume'||path==='/api/lease/keep'){status={phase:'waiting',busy:true,mine:true,deadline:Date.now()/1000+120};body={ok:true};}
  else if(path==='/api/projects')body=[];
  else throw new Error('검증되지 않은 API: '+path);
  return route.fulfill({json:structuredClone(body)});
 });
 await page.goto(process.argv[3]);
 await page.getByRole('textbox',{name:'개발 요청',exact:true}).fill('오프라인 메모 앱을 만들어주세요.');
 status={busy:true,mine:false,phase:'running'};
 await page.evaluate(()=>window.dispatchEvent(new CustomEvent('service-status',{detail:{busy:true,mine:true}})));
 await page.getByText('다른 사용자가 이용 중입니다',{exact:true}).first().waitFor();
 assert.equal(await page.getByRole('button',{name:'명세 생성 시작',exact:true}).isDisabled(),true);
 const draft=page.getByRole('textbox',{name:'개발 요청',exact:true});
 await draft.fill('점유 중에도 보존할 요청');
 for(const width of [1440,390]){
  await page.setViewportSize({width,height:width===390?844:1000});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:`.cache/ai-chat-preview/service-busy-${width}.png`,fullPage:true});
 }
 await page.setViewportSize({width:1440,height:1000});
 assert.equal(await page.getByRole('button',{name:'지식 검색',exact:true}).isDisabled(),true);
 status={busy:false,mine:false,phase:'idle'};
 await page.evaluate(()=>window.dispatchEvent(new Event('service-status')));
 await page.getByText('MAGI를 사용할 수 있습니다',{exact:true}).waitFor();
 assert.equal(await draft.inputValue(),'점유 중에도 보존할 요청');
 await draft.fill('오프라인 메모 앱을 만들어주세요.');
 await page.getByRole('button',{name:'명세 생성 시작',exact:true}).click();
 await page.getByRole('textbox',{name:'보관 기간 · 직접 입력',exact:true}).waitFor();
 await page.screenshot({path:'.cache/ai-chat-preview/questions-1440.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:'.cache/ai-chat-preview/questions-390.png',fullPage:true});
 await page.setViewportSize({width:1440,height:1000});
 await page.getByRole('textbox',{name:'보관 기간 · 직접 입력',exact:true}).fill('30일');
 await page.getByRole('button',{name:'답변 제출',exact:true}).click();
 await page.getByRole('textbox',{name:'저장 방식 · 직접 입력',exact:true}).waitFor();
 await page.waitForFunction(()=>!document.querySelector('textarea[aria-label="보관 기간 · 직접 입력"]'));
 assert.equal(calls.filter(c=>c.path==='/api/commands'&&c.data.kind==='answer')[0].data.input.length,1);
 await page.getByRole('textbox',{name:'저장 방식 · 직접 입력',exact:true}).fill('로컬 파일');
 await page.getByRole('button',{name:'답변 제출',exact:true}).click();
 await page.getByRole('button',{name:'이 명세 승인',exact:true}).waitFor();
 await page.screenshot({path:'.cache/ai-chat-preview/approval-1440.png',fullPage:true});
 await page.getByRole('button',{name:'현재 검토본 열기',exact:true}).click();
 await page.getByRole('heading',{name:'한국어 명세',exact:true}).waitFor();
 assert.equal(await page.locator('#job-actions').count(),0);
 await page.getByRole('button',{name:'대화에서 답변하기',exact:true}).click();
 assert.equal(await page.getByRole('tab',{name:'실행 이력',exact:true}).count(),0,'일반 사용자에게 내부 실행 이력이 표시되면 안 됩니다.');
 await page.getByRole('button',{name:'이 명세 승인',exact:true}).click();
 await page.getByRole('button',{name:'이어서 요청하기',exact:true}).waitFor();
 await page.screenshot({path:'.cache/ai-chat-preview/final-1440.png',fullPage:true});
 await page.getByRole('tab',{name:'명세',exact:true}).click();
 const downloaded=page.waitForEvent('download');await page.getByRole('button',{name:'Markdown 다운로드',exact:true}).click();
 const file=await downloaded;assert.equal(file.suggestedFilename(),'spec.ko.md');assert.equal(readFileSync(await file.path(),'utf8'),korean.content);
 await page.getByRole('button',{name:'English',exact:true}).click();await page.getByRole('heading',{name:'English specification',exact:true}).waitFor();
 const englishDownload=page.waitForEvent('download');await page.getByRole('button',{name:'Markdown 다운로드',exact:true}).click();
 const original=await englishDownload;assert.equal(original.suggestedFilename(),'spec.en.md');assert.equal(readFileSync(await original.path(),'utf8'),english.content);
 await page.getByRole('button',{name:'계속 사용',exact:true}).click();
 await page.getByRole('button',{name:'사용 종료',exact:true}).click();
 await page.getByRole('button',{name:'이 작업 사용권 다시 얻기',exact:true}).click();
 assert(calls.some(c=>c.path==='/api/lease/keep'));assert(calls.some(c=>c.path==='/api/lease/release'));assert(calls.some(c=>c.path==='/api/lease/resume'&&c.data.id===id));
 assert.equal(await page.evaluate(()=>window.__sockets.filter(s=>s.readyState===1).length),1,'StrictMode 재마운트 뒤 활성 소켓은 하나여야 합니다.');
 assert.equal(calls.find(c=>c.path==='/api/me').headers['x-csrf-token'],undefined);
 for(const call of calls.filter(c=>c.data)){assert.equal(call.headers['x-csrf-token'],'fixture-csrf');assert(call.headers['idempotency-key']);}
 expired=true;await page.evaluate(()=>window.__sockets.find(s=>s.readyState===1).emit({event:'job.changed'}));
 await page.getByRole('link',{name:'Google로 로그인',exact:true}).waitFor();
 assert.equal(await page.getByRole('navigation',{name:'작업 기록'}).count(),0);
 assert.equal(await page.evaluate(()=>window.__sockets.filter(s=>s.readyState===1).length),0,'세션 만료시 Workspace 소켓을 정리해야 합니다.');
 const count=calls.filter(c=>c.path==='/api/jobs').length;
 await page.reload();await page.getByRole('link',{name:'Google로 로그인',exact:true}).waitFor();
 assert.equal(calls.filter(c=>c.path==='/api/jobs').length,count,'로그인 전에는 작업 API를 호출하면 안 됩니다.');
 assert.deepEqual(errors,[]);
}finally{await browser.close();}
