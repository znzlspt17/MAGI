import {createRequire} from 'node:module';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const require=createRequire(new URL('../../../frontend/package.json',import.meta.url));
const {chromium}=require('playwright');
const output=fileURLToPath(new URL('../../../.cache/design-system-finish/pages/',import.meta.url));
await mkdir(output,{recursive:true});
const base=process.env.QA_BASE_URL || 'http://127.0.0.1:5173';
const job='/jobs/'+'a'.repeat(32);
const cases=[
 ['login','/?role=guest'],['new','/?role=user'],['questions',job+'?role=user'],
 ['review',job+'?role=user&status=PASS_PENDING_USER_APPROVAL'],['running',job+'?role=user&status=running'],
 ['failure',job+'?role=user&status=error'],['final',job+'?role=user&status=FINALIZED'],
 ['mcp','/settings/mcp?role=user'],['privacy','/privacy?role=guest'],['licenses','/licenses?role=guest'],['research','/research?role=guest'],
 ...['overview','users','data','knowledge','costs','logs'].map(view=>['admin-'+view,'/admin/'+view+'?role=admin']),
 ...['long','empty','error'].map(state=>[state,'/?role=user&qa='+state]), ['loading','/?role=user&qa=loading'],
 ['mcp-error','/settings/mcp?role=user&qa=error'],['mcp-empty','/settings/mcp?role=user&qa=empty'],
 ['knowledge-user','/?role=user'],['project-picker','/?role=user'],
];
// 범위가 제한된 마감 수정 후에는 해당 화면만 다시 캡처하고 기존 전체 목록에 합친다.
const selectedNames=new Set(process.argv.slice(2));
const selectedCases=selectedNames.size ? cases.filter(([name])=>selectedNames.has(name)) : cases;
if(selectedNames.size && selectedCases.length!==selectedNames.size)throw new Error('알 수 없는 화면 이름');
const previous=selectedNames.size ? JSON.parse(await readFile(output+'/coverage.json','utf8')) : [];
const browser=await chromium.launch({headless:true,channel:'msedge'}),records=previous.filter(record=>!selectedNames.has(record.name));
try{
 for(const width of [390,1440,1919,1920,2560]){
  const page=await browser.newPage({viewport:{width,height:width===390?844:1080},reducedMotion:'reduce'});
  let errors=[];page.on('pageerror',error=>errors.push(error.message));
  for(const [name,path] of selectedCases){
   errors=[];
   try{
    await page.goto(base+path,{waitUntil:'domcontentloaded'});
    await page.locator('#root > *').first().waitFor();
   await page.evaluate(async()=>{await document.fonts.ready; await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));});
    const expectedText={login:'Google로 로그인',new:'만들고 싶은 기능을 알려주세요',questions:'우선 지원할 사용 환경',review:'팀 기록 서비스 명세',running:'요청을 처리하고 있습니다',failure:'작업이 중단되었습니다',final:'팀 기록 서비스 명세',mcp:'문서 검색 서버',privacy:'MAGI 정보 처리 안내',licenses:'배포에 포함된 라이선스',research:'연구 출처 및 적용 방식','admin-overview':'현재 실행 1개',error:'검증용 조회 실패입니다','mcp-error':'검증용 조회 실패입니다','mcp-empty':'등록된 연결이 없습니다.'};
    if(expectedText[name])await page.getByText(expectedText[name],{exact:false}).first().waitFor();
    if((name==='long'||name==='empty') && width===390)await page.getByRole('button',{name:'메뉴 열기',exact:true}).click();
    if(name==='loading')await page.locator('html[data-qa-pending]').waitFor({state:'attached'});
    if(name==='long')await page.locator('.history nav a').nth(31).waitFor({state:'attached'});
    if(name==='empty')await page.getByText('작업 기록이 없습니다.',{exact:true}).waitFor();
    if((name==='long'||name==='empty') && width===390)await page.keyboard.press('Escape');
    if(name==='admin-users')await page.locator('.admin-user').first().waitFor({state:'attached'});
    if(name==='admin-data')await page.locator('.jobs-table-scroll tbody tr,.jobs-mobile-item').first().waitFor({state:'attached'});
    if(name==='admin-costs')await page.locator('.usage-cards').waitFor();
    if(name==='admin-logs')await page.locator('.logs-row').first().waitFor({state:'attached'});
    if(name==='admin-knowledge')await page.getByRole('heading',{name:'프로젝트 지식 그래프',exact:true}).waitFor();
    if(name==='knowledge-user'){
     if(width===390)await page.getByRole('button',{name:'메뉴 열기',exact:true}).click();
     await page.getByRole('button',{name:'지식 검색',exact:true}).click();
     await page.getByRole('heading',{name:'결정과 명세 지식 그래프',exact:true}).waitFor();
     if(width===390)await page.getByRole('dialog').waitFor({state:'hidden'});
    }
    if(name==='knowledge-user' || name==='admin-knowledge'){
     const filter=page.locator('.graph-menu > summary').first();
     if(await filter.count()){
      const shape=await filter.evaluate(element=>({height:element.getBoundingClientRect().height,centers:[...element.children].map(child=>{const box=child.getBoundingClientRect();return box.y+box.height/2;})}));
      if(shape.height<(width<768?44:36) || Math.max(...shape.centers)-Math.min(...shape.centers)>3)throw new Error('지식 필터의 크기 또는 한 줄 정렬 기준 불일치');
      await filter.press('Enter');
      if(!await filter.evaluate(element=>element.parentElement.open))throw new Error('필터 Enter 열기 실패');
      await filter.press('Space');
      if(await filter.evaluate(element=>element.parentElement.open))throw new Error('필터 Space 닫기 실패');
     }
    }
    if(name==='project-picker')await page.locator('summary').filter({hasText:'프로젝트와 공통 결정'}).click();
    await page.evaluate(()=>document.fonts.ready);
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    const data=await page.evaluate(()=>({viewport:innerWidth,scroll:document.documentElement.scrollWidth,headings:[...document.querySelectorAll('h1,h2')].map(e=>({text:e.textContent,size:getComputedStyle(e).fontSize})),bodyText:document.body.innerText.slice(0,1800)}));
    await page.screenshot({path:`${output}/${name}-${width}.png`,fullPage:true});
    const record={name,width,capturedAt:new Date().toISOString(),...data,overflow:data.scroll>width+1,errors:[...errors]};records.push(record);
    console.log(JSON.stringify({name,width,overflow:record.overflow,errors:record.errors}));
   }catch(error){records.push({name,width,errors:[...errors,error.message],overflow:false});console.log(JSON.stringify({name,width,error:error.message}));}
  }
  await page.close();
 }
}finally{await browser.close();await writeFile(output+'/coverage.json',JSON.stringify(records,null,2));}
if(records.some(record=>record.overflow||record.errors.length))process.exitCode=1;
