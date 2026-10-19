/* 관리자 화면은 기존 운영 API의 권한과 CSRF 검사를 사용한다. */
(() => {
    const $ = id => document.getElementById(id);
    let csrf = '';
    const initialControls=Array.from(document.querySelectorAll('input,select,button')).filter(control=>!control.disabled);
    initialControls.forEach(control=>control.disabled=true);
    const view=location.pathname.split('/')[2] || 'overview'; document.body.dataset.adminView=view;
    function applyView(){ document.querySelectorAll('[data-admin-section]').forEach(node=>{node.hidden=node.dataset.adminSection!==view;}); document.querySelectorAll('.admin-nav a').forEach(link=>{if(link.pathname===`/admin/${view}`) link.setAttribute('aria-current','page');}); }
    applyView();
    function text(tag, value, parent) { const node=document.createElement(tag); node.textContent=value; parent.append(node); return node; }
    async function request(path, options={}) {
        const response=await fetch(path,{credentials:'same-origin',...options,headers:{...(csrf ? {'X-CSRF-Token':csrf} : {}),...options.headers}});
        const data=await response.json().catch(()=>({}));
        if (response.status===401) { location.assign('/admin'); throw new Error('다시 로그인하세요.'); }
        if (!response.ok) throw new Error(data.error || '요청을 처리하지 못했습니다.');
        return data;
    }
    async function action(path,payload={}) {
        const buttons=Array.from(document.querySelectorAll('button')).filter(button=>!button.disabled);
        buttons.forEach(button=>button.disabled=true);
        try { return await request(path,{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()},body:JSON.stringify(payload)}); }
        finally { buttons.forEach(button=>button.disabled=false); }
    }
    window.addEventListener('unhandledrejection',event=>{ $('admin-error').textContent=event.reason?.message || '운영 요청을 처리하지 못했습니다.'; event.preventDefault(); });
    async function showAdmin() {
        const host=$('public-admin'); host.replaceChildren();
        function area(title,key){ const section=text('section','',host); section.dataset.adminSection=key; text('h2',title,section); return section; }
        let panel;
        try {
            const data=await request('/api/admin/overview');
            panel=area('운영 현황','overview');
            text('p',`사용권 상태: ${{idle:'사용 가능',waiting:'답변 대기',running:'처리 중',recovery:'복구 확인 필요'}[data.lease.phase] || data.lease.phase}`,panel);
            const stop=text('button','현재 실행 종료 요청',panel); stop.type='button'; stop.onclick=async()=>{await action('/api/admin/stop'); await showAdmin();};
            const costPanel=area('비용·한도','costs'); panel=costPanel;
            const settings=document.createElement('form'); panel.append(settings);
            const cap=text('input','',text('label','전체 일일 API 비용 상한 (US$)',settings)); cap.type='number'; cap.min='0'; cap.required=true; cap.max='10000'; cap.step='.01'; cap.value=data.daily_usd;
            text('button','상한 저장',settings).type='submit'; settings.onsubmit=async event=>{event.preventDefault(); await action('/api/admin/settings',{daily_usd:cap.value}); await showAdmin();};
            panel=area('사용자','users');
            for (const user of data.users) {
                const form=document.createElement('form'); form.className='admin-user'; panel.append(form); text('strong',user.id,form);
                const role=document.createElement('select'); role.setAttribute('aria-label','계정 역할'); form.append(role);
                for (const value of ['user','admin']) { const option=text('option',value==='admin' ? '관리자' : '일반 사용자',role); option.value=value; } role.value=user.role;
                const runs=text('input','',text('label','일일 실행 횟수',form)); runs.type='number'; runs.min='0'; runs.value=user.daily_runs;
                const usd=text('input','',text('label','일일 비용 US$',form)); usd.type='number'; usd.min='0'; usd.step='.01'; usd.value=user.daily_usd;
                const suspended=text('input','',text('label','계정 정지',form)); suspended.type='checkbox'; suspended.checked=user.suspended;
                text('button','저장 및 세션 폐기',form).type='submit';
                form.onsubmit=async event=>{event.preventDefault(); await action('/api/admin/user',{id:user.id,role:role.value,daily_runs:Number(runs.value),daily_usd:usd.value,suspended:suspended.checked}); await showAdmin();};
            }
            panel=costPanel;
            text('h3','산정 비용 및 미정산',panel);
            for (const cost of data.costs) {
                const row=text('div',`${cost.day} · ${cost.model} · ${cost.state} · 예약 $${cost.reserved} · 산정 비용 $${cost.actual ?? '미정'}`,panel);
                if (cost.state!=='settled') { const form=document.createElement('form'); row.append(form); const amount=text('input','',text('label','확인된 실제 비용 US$',form)); amount.type='number'; amount.min='0'; amount.required=true; amount.step='.00000001'; text('button','정산',form).type='submit'; form.onsubmit=async event=>{event.preventDefault(); await action('/api/admin/settle',{id:cost.id,actual:amount.value}); await showAdmin();}; }
            }
            panel=area('소유자 없는 기록','data');
            text('h3','이관 전 기록',panel);
            for (const job of data.unowned) { const form=document.createElement('form'); panel.append(form); text('span',job.id,form); const owner=text('input','',text('label','소유 사용자 ID',form)); owner.required=true; text('button','소유자 지정',form).type='submit'; form.onsubmit=async event=>{event.preventDefault(); await action('/api/admin/claim',{id:job.id,owner_id:owner.value}); await showAdmin();}; }
            panel=area('지식 색인 상태','overview');
            const retry=text('button','임베딩 색인 실행',panel); retry.type='button'; retry.onclick=async()=>{await action('/api/knowledge/retry'); await showAdmin();};
            text('p',data.embedding_status || '임베딩 오류 없음',panel); applyView();
        } catch (error) { $('admin-error').textContent=error.message; }
    }

    $('job-form').onsubmit=async event=>{
        event.preventDefault(); $('job-result').textContent='';
        try { renderJob(await request('/api/admin/job?id='+encodeURIComponent($('job-id').value.trim()))); }
        catch (error) { $('admin-error').textContent=error.message; }
    };
    const statusLabel=value=>({FINALIZED:'최종 완료',NEEDS_USER_INPUT:'요구사항 확인 필요',PASS_PENDING_USER_APPROVAL:'승인 대기',running:'처리 중',queued:'대기 중',error:'오류',CRITICAL_BLOCKED:'명세 보완 필요'})[value] || value || '미확인';
    function renderJob(job){
        const host=$('job-result');host.replaceChildren();text('h3',job.request || job.id,host);
        for(const [label,value] of [['작업 ID',job.id],['상태',statusLabel(job.status)],['소유자',job.owner_id || '미지정']]) text('p',`${label}: ${value}`,host);
        for(const [label,value] of [['최종 명세',job.final],['초안',job.candidate],['보완 보고서',job.critical]]) if(typeof value==='string'){const details=text('details','',host);text('summary',label,details);text('pre',value,details);}
        if(job.session_events?.length){const details=text('details','',host);text('summary','처리 이력',details);for(const event of job.session_events)text('p',`${event.action} · ${statusLabel(event.status)}`,details);}
    }
    let operation=null, catalog={jobs:[],pending:[]};
    function paintCatalog(){ $('cleanup-list').replaceChildren(); const query=$('cleanup-query').value.toLowerCase(), status=$('cleanup-status').value; for(const job of catalog.jobs.filter(job=>(!status || job.status===status) && (job.request || job.id).toLowerCase().includes(query))){const label=text('label','',$('cleanup-list'));const check=text('input','',label);check.type='checkbox';check.value=job.id;text('span',`${job.request || '작업'} · ${job.status || ''} · ${job.id}`,label);const open=text('button','상세 조회',label);open.type='button';open.onclick=async event=>{event.preventDefault();$('job-id').value=job.id;renderJob(await request('/api/admin/job?id='+encodeURIComponent(job.id)));};} $('cleanup-select-all').checked=false; }
    $('cleanup-query').oninput=paintCatalog; $('cleanup-status').onchange=paintCatalog; $('cleanup-select-all').onchange=()=>{ $('cleanup-list').querySelectorAll('input').forEach(input=>input.checked=$('cleanup-select-all').checked); };
    async function loadCleanup() {
        catalog=await request('/api/admin/cleanup/catalog');
        paintCatalog(); $('cleanup-pending').replaceChildren();
        for (const id of catalog.pending) {
            const retry=text('button',`남은 파일 정리 재시도 · ${id}`,$('cleanup-pending'));
            retry.onclick=async()=>{ retry.disabled=true; try { await executeCleanup({id}); } finally { retry.disabled=false; } };
        }
    }
    async function preview(scope) {
        const ids=scope==='projects' ? [$('admin-project').value].filter(Boolean) : Array.from($('cleanup-list').querySelectorAll('input:checked'),input=>input.value);
        if (scope==='jobs' && !ids.length) throw new Error('삭제할 작업을 선택하세요.');
        if (scope==='projects' && !ids.length) throw new Error('프로젝트를 선택하세요.');
        operation=await action('/api/admin/cleanup/preview',{scope,ids});
        if(scope==='projects' && operation.counts.jobs!==0) {
            operation=null;
            throw new Error('작업이 연결된 프로젝트입니다. 빈 프로젝트만 여기서 삭제할 수 있습니다.');
        }
        $('cleanup-summary').textContent=`${scope==='projects' ? '빈 프로젝트 1개 삭제\n'+ids.join('\n')+'\n' : ''}대상 작업 ${operation.counts.jobs}개 · 파일 ${operation.counts.files || 0}개\n${(operation.targets || ids).join('\n')}\n다른 작업의 출처 연결 ${operation.external_references || 0}개 제거 · 제외 폴더 ${(operation.skipped || []).length}개`+'\n삭제한 기록은 복구할 수 없습니다. 미리보기는 10분 동안 유효합니다.';
        $('cleanup-confirm-label').hidden=scope!=='all'; $('cleanup-confirm').value='';
        $('cleanup-execute').disabled=scope==='all'; $('cleanup-error').textContent='';
        $('cleanup-dialog').showModal(); $('cleanup-cancel').focus();
    }
    async function executeCleanup(payload) {
        const projectCleanup=operation?.scope==='projects';
        const result=await action('/api/admin/cleanup/execute',payload);
        $('cleanup-dialog').close(); operation=null;
        if(projectCleanup){location.assign('/admin/knowledge');return;}
        $('cleanup-notice').textContent=result.state==='completed' ? '정리를 완료했습니다.' : '파일 정리가 남았습니다. 재시도하세요.';
        await loadCleanup();
    }
    $('cleanup-refresh').onclick=loadCleanup;
    $('cleanup-selected').onclick=()=>preview('jobs');
    $('cleanup-all').onclick=()=>preview('all');
    if(view==='knowledge') {
        const remove=text('button','빈 프로젝트 삭제 미리보기',$('project-notice').parentElement);
        $('project-notice').after(remove);
        remove.type='button';
        remove.onclick=()=>preview('projects');
    }
    $('cleanup-cancel').onclick=()=>$('cleanup-dialog').close();
    $('cleanup-confirm').oninput=()=>{ $('cleanup-execute').disabled=$('cleanup-confirm').value!=='전체 기록 삭제'; };
    $('cleanup-execute').onclick=async()=>{
        $('cleanup-execute').disabled=true; $('cleanup-cancel').disabled=true;
        try { await executeCleanup({id:operation.id,confirmation:$('cleanup-confirm').value}); }
        catch (error) { $('cleanup-error').textContent=error.message; }
        finally { $('cleanup-execute').disabled=operation?.scope==='all' && $('cleanup-confirm').value!=='전체 기록 삭제'; $('cleanup-cancel').disabled=false; }
    };
    async function start() {
        const user=await request('/api/me'); csrf=user.csrf;
        if(user.role!=='admin')throw new Error('관리자 권한이 필요합니다.');
        initialControls.forEach(control=>control.disabled=false);
        $('account-identity').textContent=`사용자 ID: ${user.id} · 권한: ${user.role==='admin' ? '관리자' : '일반 사용자'}`;
        $('account-copy').onclick=async()=>{await navigator.clipboard.writeText(user.id); $('admin-error').textContent='사용자 ID를 복사했습니다.';};
        await showAdmin(); if(view==='data') await loadCleanup();
    }
    const ready=start();
    window.MagiPublic={ready,fetch:async(path,options)=>{await ready;return fetch(path,{credentials:'same-origin',...options,headers:{'X-CSRF-Token':csrf,...options?.headers}});}};
    ready.catch(error=>{ $('admin-error').textContent=error.message; });
})();
