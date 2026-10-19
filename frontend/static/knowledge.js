/* 프로젝트 선택과 지식 그래프 탐색. 저장된 텍스트는 HTML로 해석하지 않는다. */
(() => {
    const $ = (id) => document.getElementById(id);
    const admin=!!$('admin-project');
    const currentId=()=>typeof selectedId==='undefined' ? null : selectedId;
    const sessionTime=value=>value ? new Date(value).toLocaleDateString('ko-KR') : '';
    const notice = $("knowledge-notice");
    let sessionSequence = 0, sessionOwner = null, sessions = [], sequence = 0, graphSequence = 0, visibleNodes = new Map();
    const kindLabels = {decision: "결정", requirement: "요구사항", spec: "명세", input: "사용자 입력", review: "검토"};
    const edgeLabels = {evidence: "근거", derived: "도출", implemented: "반영", reviewed: "검토", superseded: "대체", reused: "재사용"};
    const statusLabels = {confirmed: "사용자 확정", proposed: "LLM 제안", assumption: "가정"};
    const colors = {decision: "#7c3aed", requirement: "#0369a1", spec: "#047857", input: "#b45309", review: "#be123c"};
    function sourceLabel(source) {
        if (source.startsWith('user_request')) return '원래 요청';
        if (source.startsWith('user_feedback')) return '수정 의견';
        if (source.startsWith('user_answer:')) return '사용자 답변 ' + source.split(':')[1];
        return source === 'system' ? '시스템 규칙' : source;
    }

    async function call(path, method = "GET", body) {
        if(admin){
            await window.MagiPublic.ready;
            const url=new URL(path,location.origin), project=$('admin-project').value;
            if(path==='/api/jobs') {if(!project)return [];url.pathname='/api/admin/jobs';}
            else if(url.pathname!=='/api/knowledge/retry') url.pathname=url.pathname.replace('/api/knowledge/','/api/admin/');
            if(!project) {if(url.pathname==='/api/admin/graph')return {nodes:[],edges:[],has_more:false}; throw new Error('프로젝트를 선택하세요.');}
            url.searchParams.set('project_id',project);
            if($('knowledge-session').value) url.searchParams.set('job_id',$('knowledge-session').value);
            path=url.pathname+url.search;
        }
        const response = await (window.MagiPublic?.fetch || fetch)(path, {method, headers: body ? {"Content-Type": "application/json"} : {}, body: body ? JSON.stringify(body) : undefined});
        const data = await response.json();
        if (!response.ok) throw new Error(response.status === 404 ? '출처가 삭제되었거나 더 이상 존재하지 않습니다. 다시 검색하세요.' : data.error || "지식 저장소에 연결하지 못했습니다.");
        return data;
    }
    function message(error) { notice.textContent = error instanceof TypeError ? '지식 화면을 준비하지 못했습니다. 새로고침 후 다시 시도하세요.' : error.message || '지식 조회에 실패했습니다.'; }
    function element(tag, text, parent) {
        const node = document.createElement(tag);
        if (text !== undefined) node.textContent = text;
        if (parent) parent.append(node);
        return node;
    }
    function button(text, action, parent) {
        const node = element("button", text, parent);
        node.type = "button";
        node.addEventListener("click", () => Promise.resolve().then(action).catch(message));
        return node;
    }
    function fillSessions(preferSelected = false) {
        const select = $('knowledge-session');
        const previous = preferSelected || !select.dataset.loaded ? currentId() || '' : select.value;
        select.dataset.loaded = 'true';
        select.replaceChildren();
        element('option', '전체 세션', select).value = '';
        for (const session of sessions) {
            element('option', `${session.request || '대화 세션'} · ${sessionTime(session.created_at)} · ${session.id.slice(0, 8)}`, select).value = session.id;
        }
        select.value = sessions.some(item => item.id === previous) ? previous : '';
    }
    async function loadSessions(preferSelected = false) {
        const ticket = ++sessionSequence;
        const items = await call('/api/jobs');
        if (ticket !== sessionSequence) return;
        sessions = items; fillSessions(preferSelected);
    }
    function params() {
        const result = new URLSearchParams();
        for (const [name, id] of [["job_id", "knowledge-session"], ["kind", "knowledge-kind"], ["status", "knowledge-status"]]) {
            if ($(id).value) result.set(name, $(id).value);
        }
        return result;
    }
    let renderer = null, scope = '', partial = false, raw = {nodes: [], edges: []};
    const container = $('knowledge-graph');
    function stopLayout() { renderer?.layout.stop(); }
    function destroyGraph() { renderer?.destroy(); renderer = null; }
    function createGraph() {
        if (renderer) return;
        renderer = new MagiKnowledgeGraph(container, {
            viewport: () => ({left: $('knowledge-list').hidden ? 20 : 336, top: 76, right: container.clientWidth - ($('graph-inspector').hidden ? 20 : 396), bottom: container.clientHeight - 76}),
            select: node => node.virtual ? showGroup(node) : showNode(node.id).catch(message),
            clear: () => { ++sequence; $('graph-inspector').hidden = true; $('graph-relation').textContent = '끌어서 이동 · 휠로 확대 · Esc 선택 해제'; },
            edge: edge => { $('graph-relation').textContent = `${renderer.display.nodes.find(n => n.id === edge.source)?.label} → ${edgeLabels[edge.kind] || edge.kind} → ${renderer.display.nodes.find(n => n.id === edge.target)?.label} · ${edge.count}개 실제 관계`; },
            stats: display => {
                notice.textContent = `화면 ${display.nodes.length}개 (명세 묶음 ${display.nodes.filter(n => n.virtual).length}개) · 조회 항목 ${display.rawCount}개 · 실제 관계 ${display.rawEdges}개${display.has_more ? ' · 100개 제한으로 일부 표시' : ''}${display.rawCount && !display.rawEdges ? ' · 현재 범위에 관계 없음' : ''}`;
                $('graph-orphans').hidden = !display.orphans.length;
                $('graph-orphans').textContent = `${renderer.showOrphans ? '접기' : '펼치기'}: 이 범위에서 연결 없는 항목 ${display.orphans.length}개`;
                $('graph-empty').hidden = !!display.nodes.length;
                $('graph-empty').textContent = display.rawCount ? '연결 없는 항목을 펼쳐보세요.' : ($('knowledge-kind').value || $('knowledge-status').value ? '현재 조회 조건에 맞는 항목이 없습니다.' : '아직 저장된 지식이 없습니다.');
            }
        });
        renderer.layout.options.spacing = Number($('graph-spacing').value); renderer.layout.options.distance = Number($('graph-distance').value);
        renderer.layout.paused = $('graph-pause').checked; renderer.labels.amount = Number($('graph-label-amount').value);
    }
    function showGroup(group) {
        ++sequence;
        const detail = $('knowledge-detail'); detail.replaceChildren(); $('graph-inspector').hidden = false; $('graph-inspector').scrollTop = 0;
        element('h3', group.label, detail); element('p', '같은 작업·문서 버전의 명세를 묶어 표시합니다.', detail);
        button('명세 묶음 펼치기', () => { renderer.expanded.add(group.id); renderer.render(raw, {merge: true, centerId: group.members[0]}); $('graph-inspector').hidden = true; }, detail);
        const list = element('ul', undefined, detail);
        group.members.forEach(id => button(MagiGraphData.title(visibleNodes.get(id)), () => showNode(id), element('li', undefined, list)));
        renderer.labels.schedule();
    }
    function renderList(nodes) {
        const list = $('knowledge-nodes'); list.replaceChildren();
        for (const node of nodes) {
            const li = element('li', undefined, list);
            button(`${kindLabels[node.kind] || node.kind} · ${node.body.slice(0, 90)}`, () => showNode(node.id), li);
            for (const match of node.matches || []) element('blockquote', match.quote, li);
        }
    }
    function renderGraph(graph, merge = false, centerId = null) {
        createGraph();
        if (!merge) { visibleNodes.clear(); raw = {nodes: [], edges: [], has_more: false}; }
        partial = !!graph.has_more || (merge && partial);
        for (const node of graph.nodes) {
            if (visibleNodes.has(node.id) || visibleNodes.size < 100) visibleNodes.set(node.id, node);
            else partial = true;
        }
        const edges = new Map((merge ? raw.edges : []).map(e => [e.id || JSON.stringify([e.source,e.target,e.kind]), e]));
        graph.edges.forEach(e => { if (visibleNodes.has(e.source) && visibleNodes.has(e.target)) edges.set(e.id || JSON.stringify([e.source,e.target,e.kind]), e); });
        raw = {nodes: [...visibleNodes.values()], edges: [...edges.values()], has_more: partial};
        renderer.render(raw, {merge, centerId}); renderList(raw.nodes);
    }
    async function expand(id, replace = false, depth = 1) {
        const ticket = ++graphSequence;
        const p = params(); p.set('node_id', id); p.set('depth', String(depth)); p.set('limit', '100');
        try {
            const graph = await call('/api/knowledge/graph?' + p);
            if (ticket !== graphSequence) return false;
            if (replace) { renderer.mode = 'detail'; renderer.labels.detail = true; $('graph-back').hidden = false; $('graph-summary').setAttribute('aria-pressed', 'false'); $('graph-detail-mode').setAttribute('aria-pressed', 'true'); }
            renderGraph(graph, !replace, id);
            return true;
        } catch (error) { if (ticket === graphSequence) message(error); return false; }
    }
    async function showNode(id) {
        const request = ++sequence; graphSequence++;
        let node;
        try { node = await call(`/api/knowledge/node?node_id=${encodeURIComponent(id)}`); }
        catch (error) { if (request === sequence) message(error); return; }
        if (request !== sequence) return;
        if ($('knowledge-session').value && node.job_id !== $('knowledge-session').value) {
            message(new Error('선택한 세션에 속하지 않는 항목입니다. 전체 세션 조회를 사용하세요.')); return;
        }
        if (!visibleNodes.has(id)) {
            if (!await expand(id, true) || request !== sequence) return;
        }
        if (!renderer.display.aliases.has(id)) { renderer.showOrphans = true; renderer.render(raw, {merge: true}); }
        if (window.matchMedia('(max-width:760px)').matches) $('knowledge-list').hidden = true;
        renderer.select(id); $('graph-inspector').hidden = false; $('graph-inspector').scrollTop = 0; renderer.labels.schedule();
        node.attrs ||= {};
        const detail = $("knowledge-detail"); detail.replaceChildren();
        element("h3", `${kindLabels[node.kind]} · ${node.active ? statusLabels[node.attrs.status] || "현재 항목" : "대체된 항목"}`, detail);
        if (node.attrs.origin === 'demo') element('p', '데모 실행에서 가져온 자료입니다.', detail);
        element("p", `세션: ${sessions.find(item => item.id === node.job_id)?.request || node.job_id}`, detail);
        element("pre", node.body, detail);
        if (node.attrs.rationale) element("p", "명시된 근거: " + node.attrs.rationale, detail);
        if (node.attrs.conditions) element("p", "적용 조건: " + node.attrs.conditions, detail);
        if (node.attrs.sources?.length) element("p", "출처: " + [...new Set(node.attrs.sources.map(sourceLabel))].join(", "), detail);
        if (node.attrs.original_text) element("pre", node.attrs.original_text, detail);
        button("주변 관계 펼치기", () => expand(id), detail);
        button("이 항목 중심으로 보기", async () => { if (await expand(id, true)) { $('graph-back').hidden = false; renderer.select(id); } }, detail);
        button("2단계 주변 보기", async () => { if (await expand(id, true, 2)) { $('graph-back').hidden = false; renderer.select(id); } }, detail);
        const relations = element("ul", undefined, detail);
        (node.edges || []).filter((edge) => edge.source === id || edge.target === id).forEach((edge) => {
            const other = edge.source === id ? edge.target : edge.source;
            const li = element("li", undefined, relations);
            const label = edge.other_body || visibleNodes.get(other)?.body || '연결된 항목 열기';
            button(`${edge.source === id ? "→" : "←"} ${edgeLabels[edge.kind] || edge.kind} · ${label.slice(0, 70)}`, () => showNode(other), li);
        });
        if (node.document !== undefined) {
            const disclosure = element("details", undefined, detail);
            element("summary", "이 버전의 명세 원문", disclosure);
            const document = element("pre", node.document, disclosure);
            if (node.document_has_more) {
                let offset = node.document_next_offset;
                const more = button("다음 내용 읽기", async () => {
                    more.disabled = true;
                    try {
                        const p = new URLSearchParams({job_id: node.job_id, path: node.attrs.artifact_path, content_hash: node.attrs.artifact_hash, offset});
                        const page = await call("/api/knowledge/document?" + p);
                        if (request !== sequence) return;
                        document.textContent += page.content; offset = page.next_offset; more.hidden = !page.has_more;
                    } finally { more.disabled = false; }
                }, disclosure);
            }
        }
    }
    async function refreshGraph() {
        const ticket = ++graphSequence; sequence++;
        if(admin){const url=new URL(location.href);url.searchParams.set('job_id',$('knowledge-session').value);url.searchParams.set('query',$('knowledge-query').value.trim());history.replaceState({},'',url);}
        const p = params(), query = $('knowledge-query').value.trim(), nextScope = p.toString();
        stopLayout();
        try {
            if (!renderer || scope !== nextScope || !query) {
                const base = new URLSearchParams(p); base.set('depth', '0'); base.set('limit', '100');
                const graph = await call('/api/knowledge/graph?' + base);
                if (ticket !== graphSequence) return;
                renderer?.clear(); renderer?.setMatches([]);
                renderGraph(graph); scope = nextScope; $('graph-inspector').hidden = true;
                $('knowledge-detail').textContent = '항목을 선택하면 근거와 원문을 확인할 수 있습니다.';
            }
            if (query) {
                p.set('query', query);
                const result = await call('/api/knowledge/search?' + p);
                if (ticket !== graphSequence) return;
                renderer.setMatches(result.nodes.map(node => node.id));
                renderList(result.nodes); $('knowledge-list').hidden = false; renderer.labels.schedule();
                notice.textContent += ` · 검색 ${result.nodes.length}개`;

            }
        } catch (error) { if (ticket === graphSequence) message(error); }
    }
    $("knowledge-form").addEventListener("submit", (event) => { event.preventDefault(); refreshGraph().catch(message); });
    $("knowledge-panel").addEventListener("toggle", () => { if ($("knowledge-panel").open && !$("knowledge-panel").hidden) refreshGraph().catch(message); else if (!$("knowledge-panel").open) { sequence++; graphSequence++; destroyGraph(); } });
    $("knowledge-retry").addEventListener("click", async () => {
        try { await call("/api/knowledge/retry", "POST", {}); notice.textContent = "미완료 청크 임베딩 재시도를 요청했습니다."; }
        catch (error) { message(error); }
    });
    if(!admin) loadSessions().then(() => { $('knowledge-panel').hidden = document.body.dataset.surface !== 'knowledge'; }).catch(message);
    else if(document.body.dataset.adminView==='knowledge') {
        const select=$('admin-project'), saved=new URLSearchParams(location.search);
        let projectSequence=0;
        async function changeProject(restore=false){
            const ticket=++projectSequence;
            sequence++;graphSequence++;sessionSequence++;visibleNodes.clear();destroyGraph();$('knowledge-nodes').replaceChildren();$('graph-inspector').hidden=true;$('knowledge-query').value=restore ? saved.get('query') || '' : '';
            const url=new URL(location.href);url.searchParams.set('project_id',select.value);if(!restore){url.searchParams.delete('job_id');url.searchParams.delete('query');}history.replaceState({},'',url);
            $('project-notice').textContent=select.value ? '프로젝트의 저장된 지식을 조회합니다.' : '조회할 프로젝트를 선택하세요.';
            await loadSessions();if(ticket!==projectSequence)return;
            if(restore)$('knowledge-session').value=saved.get('job_id') || '';
            $('knowledge-panel').hidden=!select.value; $('knowledge-panel').open=!!select.value;
            if(select.value)await refreshGraph();
        }
        select.addEventListener('change',()=>changeProject().catch(message));
        window.MagiPublic.ready.then(async()=>{
            const response=await window.MagiPublic.fetch('/api/admin/projects'); const projects=await response.json();if(!response.ok)throw new Error(projects.error);
            for(const project of projects)element('option',`${project.name} · ${project.id.slice(0,8)}`,select).value=project.id;
            select.value=projects.some(project=>project.id===saved.get('project_id')) ? saved.get('project_id') : projects[0]?.id || '';
            await changeProject(true);
        }).catch(message);
    }
    document.addEventListener('magi:session', () => {
        if (sessionOwner === currentId()) return;
        sessionOwner = currentId(); sequence++; graphSequence++;
        loadSessions(true).then(() => {
            if (!$('knowledge-panel').hidden) refreshGraph();
        }).catch(message);
    });
    document.addEventListener('magi:cleanup', () => {
        sequence++; graphSequence++; visibleNodes.clear(); destroyGraph();
        $('knowledge-nodes').replaceChildren(); $('graph-inspector').hidden = true;
        loadSessions().then(() => { if (!$('knowledge-panel').hidden) refreshGraph(); }).catch(message);
    });
    for (const [id, factor] of [['graph-zoom-in', 1.2], ['graph-zoom-out', 1 / 1.2]]) $(id).addEventListener('click', () => renderer?.zoom(factor));
    $('graph-fit').addEventListener('click', () => renderer?.fit());
    $('graph-layout').addEventListener('click', () => { if (renderer) { renderer.autoFit = true; renderer.touched = false; renderer.layout.start(); } });
    for (const [id, mode] of [['graph-summary','summary'],['graph-detail-mode','detail']]) $(id).addEventListener('click', () => {
        createGraph(); if (mode === 'summary') renderer.expanded.clear(); renderer.mode = mode; renderer.labels.detail = mode === 'detail'; renderer.render(raw);
        $('graph-summary').setAttribute('aria-pressed', String(mode === 'summary')); $('graph-detail-mode').setAttribute('aria-pressed', String(mode === 'detail'));
    });
    $('graph-orphans').addEventListener('click', () => { renderer.showOrphans = !renderer.showOrphans; renderer.render(raw); });
    $('graph-back').addEventListener('click', () => { $('graph-back').hidden = true; $('knowledge-query').value = ''; renderer.mode = 'summary'; renderer.labels.detail = false; renderer.expanded.clear(); $('graph-summary').setAttribute('aria-pressed', 'true'); $('graph-detail-mode').setAttribute('aria-pressed', 'false'); refreshGraph(); });
    $('graph-list-toggle').addEventListener('click', () => { $('knowledge-list').hidden = !$('knowledge-list').hidden; if (!$('knowledge-list').hidden && window.matchMedia('(max-width:760px)').matches) $('graph-inspector').hidden=true; renderer?.labels.schedule(); });
    $('graph-list-close').addEventListener('click', () => { $('knowledge-list').hidden = true; renderer?.labels.schedule(); });
    $('graph-detail-close').addEventListener('click', () => renderer?.clear());
    for (const [id, name] of [['graph-spacing','spacing'], ['graph-distance','distance']]) $(id).addEventListener('change', () => { if (renderer) { renderer.layout.options[name] = Number($(id).value); renderer.layout.start(); } });
    $('graph-label-amount').addEventListener('input', () => { if (renderer) { renderer.labels.amount = Number($('graph-label-amount').value); renderer.labels.schedule(); } });
    $('graph-pause').addEventListener('change', () => renderer?.layout.setPaused($('graph-pause').checked));
    for (const id of ['knowledge-session','knowledge-kind','knowledge-status']) $(id).addEventListener('change', () => {
        refreshGraph().catch(message);
    });
    for (const [kind, color] of Object.entries(MagiGraphData.colors)) { const label = element('span', kindLabels[kind], $('graph-legend')); label.style.setProperty('--node-color', color); }
    document.addEventListener('keydown', event => { if (event.key === 'Escape' && !$('knowledge-panel').hidden) { renderer?.clear(); document.querySelectorAll('.graph-menu[open]').forEach(menu => menu.open = false); } });
    document.querySelectorAll('.graph-menu').forEach(menu => menu.addEventListener('toggle', () => { if (menu.open) document.querySelectorAll('.graph-menu').forEach(other => { if (other !== menu) other.open = false; }); }));
    const resize = new ResizeObserver(() => { renderer?.resize(); });
    const visibility = new MutationObserver(() => {
        if ($('knowledge-panel').hidden) { sequence++; graphSequence++; destroyGraph(); }
        else if ($('knowledge-panel').open && !renderer) refreshGraph().catch(message);
    });
    function observeGraph() {
        resize.observe(container);
        visibility.observe($('knowledge-panel'), {attributes: true, attributeFilter: ['hidden']});
    }
    observeGraph();
    let resumeLayout = false;
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) { resumeLayout = !!renderer?.layout.running; stopLayout(); }
        else if (resumeLayout && renderer && !renderer.layout.paused) { renderer.layout.running = true; renderer.layout.started = performance.now(); renderer.layout.simulation?.restart(); resumeLayout = false; }
    });
    window.addEventListener('pagehide', () => { sequence++; graphSequence++; destroyGraph(); resize.disconnect(); visibility.disconnect(); });
    // 뒤로 가기 캐시에서 복귀해도 정리된 그래프와 관찰자를 다시 연결한다.
    window.addEventListener('pageshow', event => {
        if (!event.persisted) return;
        observeGraph();
        if (!$('knowledge-panel').hidden && $('knowledge-panel').open) refreshGraph().catch(message);
    });
})();
