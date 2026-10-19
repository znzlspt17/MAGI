import {createRequire} from 'node:module';
import {join} from 'node:path';
import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import assert from 'node:assert/strict';
const require=createRequire(join(process.argv[2],'package.json'));
const {chromium}=require('playwright');
const browser=await chromium.launch({headless:true,channel:'msedge'});
try {
    for (const width of [1440,390]) {
        const page=await browser.newPage({viewport:{width,height:900}}), errors=[], calls=[];
        page.on('pageerror',error=>errors.push(error.message));
        let fail=false, slow=false;
        await page.route('https://magi.test/**', async route=>{
            const req=route.request(), url=new URL(req.url()), path=url.pathname;
            if (path.startsWith('/admin')) return route.fulfill({contentType:'text/html',body:process.argv[4]});
            if (path.startsWith('/static/')) return route.fulfill({contentType:path.endsWith('.css')?'text/css':'text/javascript',body:readFileSync(join(process.argv[3],'frontend',path))});
            const data=req.postDataJSON(); calls.push({path,data,headers:req.headers(),query:url.searchParams});
            if(path==='/api/me' && req.headers()['x-csrf-token']!==undefined) return route.fulfill({status:403,contentType:'application/json',body:JSON.stringify({error:'초기 CSRF 헤더 금지'})});
            let body={ok:true};
            if (path==='/api/me') body={id:'owner-id',role:'admin',csrf:'fake-csrf'};
            if (path==='/api/admin/overview') body={lease:{phase:'idle'},daily_usd:'10',users:[{id:'owner-id',role:'admin',suspended:false,daily_runs:10,daily_usd:'1'}],costs:[{id:'cost',day:'today',model:'test',state:'uncertain',reserved:'1'}],unowned:[{id:'unowned'}]};
            if (path==='/api/admin/job') body={id:'job',request:'다른 사용자 작업',status:'FINALIZED'};
            if (path==='/api/admin/projects') body=[{id:'p1',name:'다른 사용자 프로젝트'},{id:'p2',name:'빈 프로젝트'}];
            if (path==='/api/admin/jobs') body=[{id:'job',request:'다른 사용자 작업'}];
            if (path==='/api/admin/graph') body={nodes:url.searchParams.get('project_id')==='p2'?[]:[{id:'n1',job_id:'job',project_id:'p1',kind:'input',body:'사용자 요구사항',active:true,attrs:{}}],edges:[],has_more:true};
            if (path==='/api/admin/search') body={nodes:[],mode:'text'};
            if (path==='/api/admin/node') body={id:'n1',job_id:'job',project_id:'p1',kind:'input',body:'사용자 요구사항',active:true,attrs:{artifact_path:'final/FINAL_AGENT_SPEC.md',artifact_hash:'fake-hash'},edges:[],document:'원문 명세',document_has_more:true,document_next_offset:12000};
            if (path==='/api/admin/document') body={content:'다음 원문 내용',has_more:false,next_offset:12008};
            if (path==='/api/admin/cleanup/catalog') body={jobs:[{id:'job',request:'삭제 대상',status:'FINALIZED'}],pending:['pending']};
            if (path==='/api/admin/cleanup/preview') body={id:'preview',scope:data.scope,targets:['job'],counts:{jobs:1},skipped:[]};
            if (path==='/api/admin/cleanup/preview' && data.scope==='projects') body={id:'project-preview',scope:'projects',targets:[],counts:{jobs:data.ids[0]==='p2'?0:1,files:0,magi_projects:1},skipped:[]};
            if (path==='/api/admin/cleanup/execute') body={state:'completed'};
            if(slow && path==='/api/admin/graph' && url.searchParams.get('project_id')==='p1') await new Promise(resolve=>setTimeout(resolve,150));
            return route.fulfill({status:fail?403:200,contentType:'application/json',body:JSON.stringify(fail?{error:'권한 확인 실패'}:body)});
        });
        await page.goto('https://magi.test/admin/overview');
        await page.getByText('사용권 상태: 사용 가능').waitFor();
        await page.getByRole('button',{name:'현재 실행 종료 요청',exact:true}).click();
        await page.getByRole('button',{name:'임베딩 색인 실행',exact:true}).click();
        await page.getByRole('link',{name:'사용자',exact:true}).click();
        await page.getByRole('button',{name:'저장 및 세션 폐기',exact:true}).click();
        await page.getByRole('link',{name:'비용·한도',exact:true}).click();
        await page.getByRole('button',{name:'상한 저장',exact:true}).click();
        await page.getByLabel('확인된 실제 비용 US$').fill('0.5');
        await page.getByRole('button',{name:'정산',exact:true}).click();
        await page.getByRole('link',{name:'작업·데이터',exact:true}).click();
        await page.locator('#cleanup-list input').waitFor();
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
        await page.screenshot({path:join(tmpdir(),`magi-admin-${width}.png`),fullPage:true});
        await page.locator('#job-id').fill('job'); await page.locator('#job-form button').click();
        await page.getByText('다른 사용자 작업',{exact:true}).waitFor();
        await page.getByLabel('소유 사용자 ID').fill('owner-id');
        await page.getByRole('button',{name:'소유자 지정',exact:true}).click();
        await page.locator('#cleanup-list input').check();
        await page.locator('#cleanup-selected').click(); await page.locator('#cleanup-dialog').waitFor();
        await page.locator('#cleanup-execute').click(); await page.locator('#cleanup-dialog').waitFor({state:'hidden'});
        await page.locator('#cleanup-all').click(); await page.locator('#cleanup-dialog').waitFor();
        assert.equal(await page.locator('#cleanup-execute').isDisabled(),true);
        await page.locator('#cleanup-confirm').fill('전체 기록 삭제');
        await page.locator('#cleanup-execute').click(); await page.locator('#cleanup-dialog').waitFor({state:'hidden'});
        await page.getByRole('button',{name:'남은 파일 정리 재시도 · pending'}).click();
        fail=true; await page.locator('#job-form button').click(); await page.getByText('권한 확인 실패').waitFor(); fail=false;
        await page.getByRole('link',{name:'지식 그래프',exact:true}).click();
        await page.waitForFunction(()=>document.querySelector('#admin-project').value==='p1' && document.querySelector('#knowledge-notice').textContent.includes('조회 항목'));
        await page.getByRole('button',{name:'빈 프로젝트 삭제 미리보기',exact:true}).click();
        await page.getByText('작업이 연결된 프로젝트입니다. 빈 프로젝트만 여기서 삭제할 수 있습니다.',{exact:true}).waitFor();
        assert.equal(await page.locator('#cleanup-dialog').isVisible(),false);
        await page.getByRole('button',{name:'목록',exact:true}).click();
        await page.getByRole('button',{name:'사용자 입력 · 사용자 요구사항',exact:true}).click();
        await page.getByText('이 버전의 명세 원문',{exact:true}).click();
        await page.getByRole('button',{name:'다음 내용 읽기',exact:true}).click();
        await page.getByText('원문 명세다음 원문 내용',{exact:true}).waitFor();
        await page.getByRole('button',{name:'주변 관계 펼치기',exact:true}).click();
        if(width===390) assert.equal(await page.locator('#knowledge-list').isVisible(),false);
        await page.screenshot({path:join(tmpdir(),`magi-admin-graph-${width}.png`),fullPage:true});
        await page.locator('#knowledge-session').selectOption('job');
        await page.waitForFunction(()=>location.search.includes('job_id=job'));
        await page.reload();
        await page.waitForFunction(()=>document.querySelector('#knowledge-session').value==='job');
        await page.locator('#admin-project').selectOption('p2');
        await page.getByText('아직 저장된 지식이 없습니다.',{exact:true}).waitFor();
        await page.getByRole('button',{name:'빈 프로젝트 삭제 미리보기',exact:true}).click();
        await page.locator('#cleanup-dialog').waitFor();
        assert.match(await page.locator('#cleanup-summary').textContent(),/빈 프로젝트 1개 삭제/);
        await page.locator('#cleanup-cancel').click();
        slow=true;
        const late=page.waitForResponse(response=>response.url().includes('/api/admin/graph?') && new URL(response.url()).searchParams.get('project_id')==='p1');
        const firstRequest=page.waitForRequest(request=>request.url().includes('/api/admin/graph?') && new URL(request.url()).searchParams.get('project_id')==='p1');
        await page.locator('#admin-project').selectOption('p1');
        await firstRequest;
        await page.locator('#admin-project').selectOption('p2');
        await late;
        assert.equal(await page.locator('#admin-project').inputValue(),'p2');
        await page.getByText('아직 저장된 지식이 없습니다.',{exact:true}).waitFor();
        for (const call of calls.filter(c=>c.data)) assert.equal(call.headers['x-csrf-token'],'fake-csrf');
        assert(calls.some(c=>c.path==='/api/admin/graph' && c.query.get('project_id')==='p1'));
        assert(calls.some(c=>c.path==='/api/admin/document' && c.query.get('project_id')==='p1'));
        assert.deepEqual(errors,[]);
        await page.close();
    }
    // 이전 템플릿과 새 스크립트를 함께 제공하는 재시작 전 상황을 재현한다.
    const page=await browser.newPage(), errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    let html=readFileSync(join(process.argv[3],'frontend/templates/index.html'),'utf8')
        .replace(/<p id="account-identity"><\/p><button id="account-copy"[^>]*>[^<]*<\/button>/,'')
        .replace(/<a id="admin-open"[^>]*>[^<]*<\/a>/,'<button id="admin-open" hidden>서비스 운영</button>')
        .replace("{% include '_knowledge.html' %}",readFileSync(join(process.argv[3],'frontend/templates/_knowledge.html'),'utf8'))
        .replace(/<script\b[^>]*>[\s\S]*?<\/script>/g,'')
        .replace(/{{ url_for\('static', filename='([^']+)'\) }}/g,'/static/$1')
        .replace('</body>','<script src="/static/public.js"></script></body>');
    await page.route('https://magi.test/**',async route=>{
        const path=new URL(route.request().url()).pathname;
        if(path==='/') return route.fulfill({contentType:'text/html',body:html});
        if(path==='/static/public.js') return route.fulfill({contentType:'text/javascript',body:readFileSync(join(process.argv[3],'frontend/static/public.js'))});
        const responses={'/api/auth/info':{public:true,login_available:true},'/api/me':{id:'owner-id',role:'admin',csrf:'fake-csrf'},'/api/service/status':{busy:false},'/api/me/usage':{runs:0,remaining_runs:3,resets_at:'2026-10-20'}};
        return route.fulfill({contentType:'application/json',body:JSON.stringify(responses[path] || {})});
    });
    await page.goto('https://magi.test/');
    await page.waitForFunction(()=>window.MagiPublic?.authenticated && document.body.dataset.auth==='signed-in' && document.querySelector('#account-identity')?.textContent.includes('owner-id'));
    assert.equal(await page.locator('#admin-open').getAttribute('href'),'/admin');
    assert.equal(await page.locator('#account-copy').count(),1);
    await page.evaluate(()=>window.MagiPublic.ready);
    assert.equal(await page.locator('body').getAttribute('data-auth'),'signed-in');
    assert.deepEqual(errors,[]);
    await page.close();
} finally { await browser.close(); }

