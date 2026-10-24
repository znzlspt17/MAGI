import {createRequire} from 'node:module';
import {join} from 'node:path';
import {mkdirSync} from 'node:fs';
import assert from 'node:assert/strict';
const {chromium}=createRequire(join(process.argv[2],'package.json'))('playwright');
const browser=await chromium.launch({headless:true,channel:process.platform==='win32'?'msedge':undefined});
try {
 mkdirSync('.cache/ai-chat-preview',{recursive:true});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],mutations=[];
 page.on('pageerror',error=>errors.push(error.message));
 await page.addInitScript(()=>{
  window.__sockets=[];
  window.WebSocket=class{static OPEN=1;readyState=0;constructor(){window.__sockets.push(this);setTimeout(()=>{if(this.readyState===3)return;this.readyState=1;this.onopen?.({});},0);}close(){this.readyState=3;}emit(value){this.onmessage?.({data:JSON.stringify(value)});}};
 });
 const id='a'.repeat(32),otherId='b'.repeat(32);
 const events=Array.from({length:8},(_,index)=>({id:'event-'+index,action:index?'revise':'generate',input:index?{feedback:`${index}번째 검토 의견입니다.\n메모를 저장하고 다시 찾는 흐름과 백업 정책을 구체화해주세요.`}:{request:'오프라인 메모 앱의 명세를 함께 만들어주세요.'},summary:`${index+1}번째 검토 내용을 반영했습니다.\n저장 방식과 검색, 보관 기간에 대한 요구사항을 정리했습니다.\n서로 다른 사용자 환경에서도 이해할 수 있도록 검토본에 명확히 기록했습니다.`,document_step_id:index===0?'old-doc':index===7?'current-doc':undefined,started_at:`2026-10-21T00:0${index}:00Z`}));
 const job={id,request:'오프라인 메모 앱의 명세를 함께 만들어주세요.',status:'FINALIZED',execution_id:'current',can_continue:true,message:'최종 명세가 준비되었습니다.',session_events:events,latest_completed:{step_id:'current-doc'},execution_graph:{nodes:[{id:'old-doc',execution_id:'past',stage:'approve',status:'completed',has_document:true,detail_available:true},{id:'current-doc',execution_id:'current',stage:'approve',status:'completed',has_document:true,detail_available:true}]}};
 const other={id:otherId,request:'다른 프로젝트의 요청',status:'FINALIZED',execution_id:'other',can_continue:true};
 events[1].action='answer';events[1].input={answers:[{question_id:'Q1',question:'긴 질문 원문 '+ '질문내용'.repeat(100),answer:'첫 답변\n줄바꿈 유지'},{question_id:'Q2',question:'두 번째 질문 원문',answer:'두 번째 답변'},{question_id:'Q3',answer:'질문 없는 답변'}]};
 await page.route('**/api/**',route=>{
  const request=route.request(),path=new URL(request.url()).pathname;
  let body;
  if(path==='/api/auth/info')body={public:true,login_available:true};
  else if(path==='/api/me')body={id:'fixture-user',role:'user',csrf:'fixture-csrf'};
  else if(path==='/api/service/status')body={ready:true,active_count:0,queued_count:0,max_parallel:2,own_active_count:0};
  else if(path==='/api/me/usage')body={runs:1,remaining_runs:2};
  else if(path==='/api/jobs')body=[job,other];
  else if(path==='/api/jobs/'+otherId)body=other;
  else if(path==='/api/jobs/'+id)body=job;
  else if(path.includes('/steps/')){
   const step=path.split('/steps/')[1].split('/')[0];
   const doc={content:`# ${step==='old-doc'?'이전':'현재'} 명세\n\n저장된 실제 검토본입니다.`,language:'ko',source_hash:step,filename:step+'.md'};
   body=path.endsWith('/document')?doc:{document:doc,result:{summary:'저장된 명세'}};
  }else if(path === '/api/commands' && request.postDataJSON().kind === 'continue'){mutations.push(request.postDataJSON());return route.fulfill({status:503,json:{error:'테스트용 일시적 연결 오류'}});}
  else throw new Error('unexpected request '+path);
  return route.fulfill({json:structuredClone(body)});
 });
 const refresh=()=>page.evaluate(()=>window.__sockets.find(socket=>socket.readyState===1).emit({event:'job.changed'}));
 await page.goto(process.argv[3]+'/jobs/'+id);
 await page.getByRole('button',{name:'이어서 요청하기',exact:true}).waitFor();
 assert.equal(await page.getByRole('tab',{name:'대화',exact:true}).getAttribute('aria-selected'),'true');
 assert.equal(await page.getByRole('tab',{name:'실행 이력',exact:true}).count(),0);
 assert.equal(await page.locator('.chat-turn').count(),17);
 const expandedWidth=await page.locator('.workspace-content').evaluate(e=>e.getBoundingClientRect().width);
 await page.getByRole('button',{name:'메뉴 접기',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-slot="sidebar-gap"]').getBoundingClientRect().width===0);
 assert.equal(await page.locator('[data-slot="sidebar-container"]').isVisible(),false);
 assert(await page.locator('.workspace-content').evaluate(e=>e.getBoundingClientRect().width)>expandedWidth);
 assert.equal(await page.locator('[data-slot="sidebar-container"]').getAttribute('inert'),'');
 await page.getByRole('button',{name:'메뉴 열기',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('[data-slot="sidebar-gap"]').getBoundingClientRect().width>200);
 assert.equal(await page.locator('#job-actions').count(),1);
 for(const width of [1440,768,390]){
  const height=width===390?844:1000;
  await page.setViewportSize({width,height});
  const references=page.getByRole('button',{name:'답변 대상 질문',exact:true});
  assert.equal(await references.count(),2);
  assert.equal(await references.first().getAttribute('aria-expanded'),'false');
  await references.first().click();
  assert.equal(await references.first().getAttribute('aria-expanded'),'true');
  assert.equal(await references.nth(1).getAttribute('aria-expanded'),'false');
  await page.locator('.chat-answer').first().scrollIntoViewIfNeeded();
  assert.equal(await page.locator('.chat-answer .chat-message-text').first().textContent(),'첫 답변\n줄바꿈 유지');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${width}px 질문 펼침 가로 넘침`);
  await page.screenshot({path:`.cache/ai-chat-preview/question-reference-${width}.png`,fullPage:true});
  await references.first().click();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${width}px 가로 넘침`);
  for(const element of [page.getByRole('textbox',{name:'추가 요청 내용',exact:true}),page.getByRole('button',{name:'이어서 요청하기',exact:true})]){
   const box=await element.boundingBox();assert(box&&box.y>=0&&box.y+box.height<=height,`${width}px에서 입력과 전송 버튼이 동시에 viewport 안에 있어야 합니다.`);
  }
  await page.screenshot({path:`.cache/ai-chat-preview/conversation-${width}.png`,fullPage:true});
 }
 await page.setViewportSize({width:1440,height:1000});
 const input=page.getByRole('textbox',{name:'추가 요청 내용',exact:true});
 await input.fill('문서 탭에 다녀와도 유지되는 초안');
 await page.locator('.chat-turn.magi').first().getByRole('button',{name:'이 시점의 명세 열기'}).click();
 await page.getByRole('heading',{name:'이전 명세',exact:true}).waitFor();
 assert.equal(await page.locator('#job-actions').count(),0,'과거 문서에는 승인·수정 폼을 두지 않는다.');
 events.at(-1).summary+='\n백그라운드 갱신';await refresh();
 await page.getByRole('heading',{name:'이전 명세',exact:true}).waitFor();
 assert.equal(await page.getByRole('tab',{name:'명세',exact:true}).getAttribute('aria-selected'),'true');
 await page.getByRole('navigation',{name:'작업 기록'}).getByRole('link').filter({hasText:'다른 프로젝트'}).click();
 await page.getByRole('textbox',{name:'추가 요청 내용'}).waitFor();
 await page.getByRole('navigation',{name:'작업 기록'}).getByRole('link').filter({hasText:'오프라인 메모'}).click();
 await page.getByRole('heading',{name:'이전 명세',exact:true}).waitFor();
 await page.getByRole('button',{name:'대화에서 답변하기'}).click();
 assert.equal(await input.inputValue(),'문서 탭에 다녀와도 유지되는 초안');
 const viewport=page.locator('.chat-viewport');
 await viewport.hover();await page.mouse.wheel(0,-20000);
 await page.waitForFunction(()=>document.querySelector('.chat-viewport').scrollTop<10);
 events.push({id:'new-event',action:'revise',input:{feedback:'추가 검토 의견'},summary:'새로운 검토 결과가 도착했습니다.'});
 await refresh();
 await page.getByText('새로운 검토 결과가 도착했습니다.',{exact:true}).waitFor({state:'attached'});
 assert(await viewport.evaluate(element=>element.scrollTop<100),'과거 메시지를 읽는 동안 아래로 강제 이동하지 않는다.');
 await page.getByRole('button',{name:'최신 메시지로 이동',exact:true}).click();
 await page.waitForFunction(()=>{const element=document.querySelector('.chat-viewport');return element.scrollHeight-element.clientHeight-element.scrollTop<60;});
 await input.press('Enter');
 assert.equal(mutations.length,0,'Enter 단독은 전송하지 않는다.');
 await input.press('Control+Enter');
 await page.getByText('테스트용 일시적 연결 오류',{exact:true}).waitFor();
 assert.equal(mutations.length,1);assert.equal(mutations[0].execution_id,'current');
 assert((await input.inputValue()).includes('문서 탭에 다녀와도 유지되는 초안'));
 assert.deepEqual(errors,[]);
} finally { await browser.close(); }
