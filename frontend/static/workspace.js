/* 단계별 작업 화면과 문서 탐색. */
(() => {
    const $ = id => document.getElementById(id);
    let surface = 'workspace', worktab = 'document', tabOwner = null, manual = false;
    const sessionTabs = new Map();
    const text = (tag, value, parent) => {
        const node = document.createElement(tag); node.textContent = value;
        if (parent) parent.append(node); return node;
    };
    function paintSurface() {
        document.body.dataset.surface = surface;
        document.body.dataset.worktab = worktab;
        $('knowledge-panel').hidden = surface !== 'knowledge';
        if (surface === 'knowledge') $('knowledge-panel').open = true;
        document.querySelectorAll('button[data-surface]').forEach(button => {
            if (button.dataset.surface === surface) button.setAttribute('aria-current', 'page');
            else button.removeAttribute('aria-current');
        });
        document.querySelectorAll('button[data-worktab]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.worktab === worktab)));
    }
    async function showWorktab(tab) {
        worktab = tab; manual = true; paintSurface();
        if (!selectedJob) return;
        if (tab === 'history') return;
        const nodes = graphNodes(selectedJob);
        const node = tab === 'review' || tab === 'conversation' ? defaultStep(nodes) : [...nodes].reverse().find(n => n.has_document && n.detail_available);
        selectedTab = tab === 'document' ? 'document' : tab === 'conversation' ? 'result' : 'issues';
        if (node) await selectStep(node.id, true);
        else if (selectedStepId) renderStepDetail(nodeById(selectedStepId));
    }
    window.MagiWorkspace = {
        preferredTab: () => worktab === 'document' ? 'document' : worktab === 'review' ? 'issues' : null,
        deleted(ids) {
            documentTranslations.clear(); documentRequestSequence++; requestSequence++; stepRequestSequence++;
            if (ids.includes(selectedId)) {
                selectedId = null; selectedJob = null; selectedStepId = null; selectedStepDetail = null;
                $('job-workspace').hidden = true; $('status-summary').hidden = true;
                $('request-form').hidden = false; renderHeader(null);
            }
            document.dispatchEvent(new Event('magi:cleanup'));
        },
        rendered(job) {
            if (tabOwner !== job.id) {
                if (tabOwner) sessionTabs.set(tabOwner, {worktab, manual});
                const saved = sessionTabs.get(job.id);
                tabOwner = job.id; manual = saved?.manual || false; worktab = saved?.worktab || 'document';
            }
            if (!manual) worktab = job.status === 'NEEDS_USER_INPUT' ? 'review' : ['PASS_PENDING_USER_APPROVAL','FINALIZED'].includes(job.status) ? 'document' : 'conversation';
            const latestStage=graphNodes(job).at(-1)?.stage || '';
            const phase = job.status === 'FINALIZED' ? 3 : job.status==='NEEDS_USER_INPUT' ? 1 : job.status === 'PASS_PENDING_USER_APPROVAL' || /compile|spec|approve/.test(latestStage) ? 2 : job.status==='queued' ? 0 : 1;
            document.querySelectorAll('.workflow-progress li').forEach((item,index)=>{ if(index===phase) item.setAttribute('aria-current','step'); else item.removeAttribute('aria-current'); });
            if (!['queued', 'running'].includes(job.status) && $('notice').textContent === '작업을 대기열에 넣었습니다.') setNotice('');
            paintSurface();
            document.dispatchEvent(new Event('magi:session'));
        }
    };
    document.querySelectorAll('button[data-surface]').forEach(button => button.addEventListener('click', () => {
        surface = button.dataset.surface; paintSurface();
    }));
    document.querySelectorAll('button[data-worktab]').forEach(button => button.addEventListener('click', () => showWorktab(button.dataset.worktab).catch(showError)));
    $('new-job').addEventListener('click', () => { surface = 'workspace'; document.querySelectorAll('.workflow-progress li').forEach((item,index)=>{if(index===0)item.setAttribute('aria-current','step');else item.removeAttribute('aria-current');}); paintSurface(); });
    const sidebar = document.querySelector('.workspace-sidebar');
    sidebar.classList.add('history-collapsed');
    $('history-toggle').addEventListener('click', () => {
        const expanded = sidebar.classList.toggle('history-collapsed') === false;
        $('history-toggle').setAttribute('aria-expanded', String(expanded));
        $('history-toggle').textContent = expanded ? '작업 목록 접기' : '작업 목록 펼치기';
    });
    $('job-list').addEventListener('click', () => { surface = 'workspace'; paintSurface(); });
    for (const id of ['history-query', 'history-status']) $(id).addEventListener('input', renderHistory);
    function showError(error) { setNotice(error.message); }
    // 목차는 현재 보이는 언어와 문서에서만 만든다.
    const observer = new MutationObserver(() => {
        const view = $('detail-content').querySelector('.markdown-view');
        if (!view || view.querySelector('.document-toc') || !view.querySelector('h2')) return;
        const toc = document.createElement('details'); toc.className = 'document-toc';
        text('summary', '문서 목차', toc);
        view.querySelectorAll('h2,h3').forEach((heading, i) => {
            heading.id = `document-heading-${i}`;
            const link = text('a', heading.textContent, toc); link.href = `#${heading.id}`;
        });
        view.prepend(toc);
    });
    observer.observe($('detail-content'), {childList: true, subtree: true});
    paintSurface();
})();
