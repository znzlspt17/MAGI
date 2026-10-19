/* 공개 서비스의 세션·CSRF·독점 안내를 모든 화면에서 공유한다. */
(() => {
    const nativeFetch = window.fetch.bind(window), $ = id => document.getElementById(id);
    const state = {public: true, authenticated: false, user: null, status: {busy: false}};
    const api = window.MagiPublic = state;
    // 실행 중인 게이트웨이가 이전 템플릿을 캐시했어도 새 계정 UI를 구성한다.
    const account = $('public-account');
    if (account && !$('account-identity')) {
        const identity = document.createElement('p'); identity.id = 'account-identity'; account.prepend(identity);
    }
    if (account && !$('account-copy')) {
        const copy = document.createElement('button'); copy.id = 'account-copy'; copy.type = 'button'; copy.textContent = '사용자 ID 복사'; account.append(copy);
    }
    if (account && $('admin-open')?.tagName !== 'A') {
        const link = document.createElement('a'); link.id = 'admin-open'; link.href = '/admin'; link.textContent = '관리자 페이지'; link.hidden = true;
        if ($('admin-open')) $('admin-open').replaceWith(link); else account.append(link);
    }
    const pendingRequests = new Map();
    let csrf = '', timer, usageTimer, draftKey = '';
    function text(tag, value, parent) { const node = document.createElement(tag); node.textContent = value; parent.append(node); return node; }
    async function raw(path, options = {}) {
        const response = await nativeFetch(path, {credentials: 'same-origin', ...options});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) { const error = new Error(`${data.error || '요청을 처리하지 못했습니다.'}${data.request_id ? ` (문의 번호 ${data.request_id})` : ''}`); error.status = response.status; throw error; }
        return data;
    }
    api.fetch = async (path, options = {}) => {
        await api.ready;
        const method = (options.method || 'GET').toUpperCase(), headers = new Headers(options.headers || {});
        const signature = `${method}:${path}:${options.body || ''}`;
        if (state.public && !['GET','HEAD','OPTIONS'].includes(method)) {
            headers.set('X-CSRF-Token', csrf);
            if (!pendingRequests.has(signature)) pendingRequests.set(signature, crypto.randomUUID());
            headers.set('Idempotency-Key', options.requestKey || pendingRequests.get(signature));
        }
        const response = await nativeFetch(path, {credentials:'same-origin', ...options, headers});
        if (response.ok || response.status < 500) pendingRequests.delete(signature);
        if (state.public && response.status === 401) signedOut();
        return response;
    };
    async function action(path, payload = {}) {
        const response = await api.fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || '요청을 처리하지 못했습니다.');
        return data;
    }
    function signedOut() {
        if (/^\/jobs\/[0-9a-f]{32}$/.test(location.pathname)) sessionStorage.setItem('magi:return-path',location.pathname);
        state.authenticated = false; csrf = '';
        document.body.dataset.auth = 'signed-out';
        clearInterval(timer); clearInterval(usageTimer);
        document.dispatchEvent(new Event('magi:signed-out'));

    }
    api.renderStatus = value => {
        state.status = value;
        const seconds = value.deadline ? Math.max(0, Math.ceil(value.deadline - Date.now()/1000)) : null;
        $('service-state').textContent = value.recovering ? '서비스 복구 확인 중입니다.' : !value.busy ? 'MAGI를 사용할 수 있습니다.' : value.mine ? seconds === null ? '내 작업을 처리 중입니다.' : `내 작업 응답 대기 · ${seconds}초 후 사용권 해제` : '다른 사용자가 사용 중입니다. 내 기록은 열람할 수 있습니다.';
        $('lease-warning').textContent = seconds !== null && seconds <= 30 ? '곧 사용권이 해제됩니다. 계속하려면 “계속 사용”을 누르세요.' : '';
        $('lease-keep').hidden = !value.mine || seconds === null;
        $('lease-release').hidden = !value.mine;
        $('lease-resume').hidden = value.busy || !/^\/jobs\/[0-9a-f]{32}$/.test(location.pathname);
        document.body.dataset.serviceBusy = value.busy && !value.mine ? 'true' : 'false';
        updateControls();
    };
    function updateControls() {
        if (!state.public || !state.authenticated) return;
        const blocked = state.status.busy && !state.status.mine;
        document.querySelectorAll('#generate-button,#job-actions button,[data-surface="knowledge"],#knowledge-retry,#cleanup-jobs,#cleanup-all').forEach(button => {
            if (blocked && !button.disabled) { button.dataset.serviceDisabled = 'true'; button.disabled = true; }
            else if (!blocked && button.dataset.serviceDisabled) { delete button.dataset.serviceDisabled; button.disabled = false; }
        });
    }
    async function loadUsage() {
        try { const usage = await raw('/api/me/usage'); $('account-usage').textContent = `오늘 실행 ${usage.runs}회 · 잔여 ${usage.remaining_runs}회${usage.limit_reached ? ' · 비용 한도 도달' : ''} · 갱신 ${new Date(usage.resets_at).toLocaleString('ko-KR')}`; }
        catch (error) { if (error.status === 401) signedOut(); }
    }
    api.ready = (async () => {
        try {
            const info = await raw('/api/auth/info'); state.public = info.public;
            if (!info.public) { document.body.dataset.auth = 'local'; return; }
            $('google-login').hidden = !info.login_available;
            $('login-state').textContent = info.login_available ? 'Google 계정으로 로그인하세요.' : 'Google 로그인 설정이 준비되지 않았습니다. 운영자에게 문의하세요.';
            try { state.user = await raw('/api/me'); }
            catch (_) { signedOut(); return; }
            csrf = state.user.csrf; delete state.user.csrf;
            state.authenticated = true; draftKey = `magi:draft:${state.user.id}`;
            const returnPath=sessionStorage.getItem('magi:return-path');
            if (location.pathname==='/' && /^\/jobs\/[0-9a-f]{32}$/.test(returnPath || '')) history.replaceState({},'',returnPath);
            sessionStorage.removeItem('magi:return-path');
            document.body.dataset.auth = 'signed-in';
            $('account-identity').textContent = `사용자 ID: ${state.user.id} · 권한: ${state.user.role==='admin' ? '관리자' : '일반 사용자'}`;
            $('admin-open').hidden = state.user.role !== 'admin';
            document.querySelector('[data-worktab="history"]').hidden = state.user.role !== 'admin';
            $('knowledge-retry').hidden = state.user.role !== 'admin';
            $('summary-usage').closest('div').hidden = true;
            $('request-text').value = sessionStorage.getItem(draftKey) || '';
            api.renderStatus(await raw('/api/service/status')); await loadUsage();
            usageTimer = setInterval(loadUsage, 30000);
            timer = setInterval(async () => {
                try { api.renderStatus(await raw('/api/service/status')); }
                catch (error) { if (error.status === 401) signedOut(); }
            }, 2000);
        } catch (error) { signedOut(); $('login-state').textContent = error.message || '서비스에 연결하지 못했습니다. 잠시 후 새로고침하세요.'; }
    })();
    $('account-copy').addEventListener('click', async () => { try { await navigator.clipboard.writeText(state.user.id); $('lease-warning').textContent = '사용자 ID를 복사했습니다.'; } catch (_) { $('lease-warning').textContent = '표시된 ID를 직접 복사하세요.'; } });
    $('request-text').addEventListener('input', () => { if (draftKey) sessionStorage.setItem(draftKey, $('request-text').value); });
    document.addEventListener('input', event => {
        if (!draftKey || !event.target.matches('#job-actions textarea')) return;
        const key = `${draftKey}:${location.pathname}:${event.target.getAttribute('aria-label') || event.target.id || 'answer'}`;
        sessionStorage.setItem(key, event.target.value);
    });
    const observer = new MutationObserver(() => {
        updateControls();
        if (!draftKey) return;
        document.querySelectorAll('#job-actions textarea').forEach(input => {
            if (input.dataset.draftLoaded) return;
            input.dataset.draftLoaded = 'true';
            const key = `${draftKey}:${location.pathname}:${input.getAttribute('aria-label') || input.id || 'answer'}`;
            if (!input.value && sessionStorage.getItem(key)) { input.value=sessionStorage.getItem(key); input.dispatchEvent(new Event('input',{bubbles:true})); }
        });
    });
    observer.observe($('job-actions'), {childList:true,subtree:true});
    function handle(button, callback) { $(button).addEventListener('click', async () => { try { await callback(); api.renderStatus(await raw('/api/service/status')); } catch (error) { $('lease-warning').textContent=error.message; } }); }
    handle('lease-keep', () => action('/api/lease/keep'));
    handle('lease-release', () => action('/api/lease/release'));
    handle('lease-resume', () => action('/api/lease/resume',{id:location.pathname.split('/').pop()}));
    $('account-logout').addEventListener('click', async () => { try { await action('/api/logout'); } finally { signedOut(); } });
    window.addEventListener('beforeunload', event => { if (state.authenticated && document.activeElement?.matches('textarea') && document.activeElement.value) { event.preventDefault(); event.returnValue=''; } });
    window.addEventListener('pagehide', () => { clearInterval(timer); clearInterval(usageTimer); observer.disconnect(); });
})();
