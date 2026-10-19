/* 표시용 집계만 수행한다. 원본 노드와 관계는 변경하지 않는다. */
((root) => {
    const kinds = {input: '사용자 입력', decision: '결정', requirement: '요구사항', spec: '명세', review: '검토'};
    const colors = {input: '#bf8b41', decision: '#9270c6', requirement: '#438b9d', spec: '#55a28b', review: '#bd708b'};
    const sections = {architecture: '아키텍처', test_plan: '테스트 계획', manual_verification_checklist: '수동 검증', acceptance_criteria: '수용 기준', instructions_for_ai_coding_agent: '구현 지침', implementation_order: '구현 순서', persistence_artifact_policy: '저장 정책', configuration_policy: '설정 정책', error_handling_policy: '오류 처리', data_flow: '데이터 흐름', module_responsibilities: '모듈 책임', output_contract: '출력 규약', input_contract: '입력 규약', forbidden_behaviors: '금지 동작', evidence_summary: '근거 요약', definitions: '용어 정의', in_scope: '포함 범위', user_intent: '사용자 의도', background: '배경', mission: '목표'};
    function title(node) {
        const attrs = node.attrs || {};
        if (attrs.requirement_id) return attrs.requirement_id;
        if (node.logical_key === 'user_request') return '원래 요청';
        if (node.logical_key === 'user_feedback') return '수정 의견';
        if (node.kind === 'input' && attrs.question) return attrs.question.slice(0, 25);
        if (node.kind === 'spec' && attrs.section) {
            const section = sections[attrs.section] || attrs.section.replace(/^#+\s*\d*\.?\s*/, '').slice(0, 25);
            const item = node.logical_key?.startsWith('item:') ? node.logical_key.slice(5) : '';
            return section + (item ? ' · ' + item : '');
        }
        return (node.body || '').replace(/^\s*(?:Assumption\s*:?|가정\s*:?)\s*/i, '').replace(/\s+/g, ' ').slice(0, 27) || kinds[node.kind] || '지식';
    }
    function build(graph, {mode = 'summary', expanded = new Set(), showOrphans = false} = {}) {
        const originals = new Map(graph.nodes.map(n => [n.id, n]));
        const degree = new Map(graph.nodes.map(n => [n.id, 0]));
        const edges = graph.edges.filter(e => originals.has(e.source) && originals.has(e.target));
        for (const edge of edges) {
            degree.set(edge.source, degree.get(edge.source) + 1);
            degree.set(edge.target, degree.get(edge.target) + 1);
        }
        const orphans = graph.nodes.filter(n => degree.get(n.id) === 0);
        const nodes = new Map(), aliases = new Map();
        for (const node of graph.nodes) {
            if (!showOrphans && !degree.get(node.id)) continue;
            const attrs = node.attrs || {};
            // 문서 해시가 없으면 버전을 추측해서 다른 항목과 합치지 않는다.
            const group = node.kind === 'spec' && attrs.artifact_hash && node.job_id
                ? 'group:' + JSON.stringify([node.job_id, attrs.artifact_path || '', attrs.artifact_hash]) : null;
            const id = mode === 'summary' && group && !expanded.has(group) ? group : node.id;
            aliases.set(node.id, id);
            if (!nodes.has(id)) nodes.set(id, {id, kind: node.kind, color: colors[node.kind] || '#8491a5',
                label: title(node), members: [], virtual: id === group, active: node.active, degree: 0});
            const display = nodes.get(id); display.members.push(node.id);
            if (display.virtual) display.label = `명세 · ${display.members.length}개`;
        }
        const links = new Map(); let internalEdges = 0;
        for (const edge of edges) {
            const source = aliases.get(edge.source), target = aliases.get(edge.target);
            if (!source || !target) continue;
            if (source === target) { internalEdges++; continue; }
            const id = 'link:' + JSON.stringify([source, target, edge.kind]);
            if (!links.has(id)) links.set(id, {id, source, target, kind: edge.kind, count: 0, members: []});
            const display = links.get(id); display.count++; display.members.push(edge.id);
        }
        for (const edge of links.values()) {
            nodes.get(edge.source).degree += edge.count; nodes.get(edge.target).degree += edge.count;
        }
        return {nodes: [...nodes.values()], edges: [...links.values()], originals, aliases, orphans,
            rawCount: graph.nodes.length, rawEdges: edges.length, internalEdges, has_more: !!graph.has_more};
    }
    const api = {build, title, colors, kinds};
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    else root.MagiGraphData = api;
})(typeof window === 'undefined' ? globalThis : window);
