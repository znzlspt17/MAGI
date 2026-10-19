/* d3-force의 가변 좌표는 서버 응답과 분리된 복사본에만 기록한다. */
window.MagiGraphLayout = class {
    constructor(cy, changed, settled) {
        this.cy = cy; this.changed = changed; this.settled = settled;
        this.options = {spacing: 26, distance: 95}; this.paused = false;
        this.reduced = matchMedia('(prefers-reduced-motion: reduce)');
        this.motionChange = () => { if (this.running) this.start(); };
        this.reduced.addEventListener('change', this.motionChange);
    }
    stop() { if (this.simulation) this.simulation.stop(); this.running = false; }
    start({fixed = new Set(), warm = false} = {}) {
        this.stop(); const cy = this.cy; this.started = performance.now();
        this.nodes = cy.nodes().map(n => ({id: n.id(), ...n.position(), fx: fixed.has(n.id()) ? n.position('x') : null, fy: fixed.has(n.id()) ? n.position('y') : null}));
        this.byId = new Map(this.nodes.map(n => [n.id, n]));
        const links = cy.edges().map(e => ({source: e.source().id(), target: e.target().id(), count: e.data('count')}));
        this.simulation = d3.forceSimulation(this.nodes).stop()
            .force('charge', d3.forceManyBody().strength(-230).distanceMax(900))
            .force('link', d3.forceLink(links).id(n => n.id).distance(this.options.distance).strength(.18))
            .force('collide', d3.forceCollide(this.options.spacing).iterations(2))
            .force('x', d3.forceX(0).strength(.025)).force('y', d3.forceY(0).strength(.025))
            .velocityDecay(.5).alphaDecay(.075).alphaMin(.005);
        const paint = () => {
            cy.batch(() => cy.nodes().forEach(node => {
                if (!node.grabbed()) { const p = this.byId.get(node.id()); node.position({x: p.x, y: p.y}); }
            }));
            this.changed();
        };
        const finish = () => { this.running = false; paint(); this.settled(Math.round(performance.now() - this.started)); };
        this.simulation.on('tick', paint).on('end', finish);
        if (this.paused) { paint(); this.settled(0); return; }
        if (this.reduced.matches) { this.simulation.tick(100); finish(); return; }
        if (warm) { this.simulation.tick(45); paint(); }
        this.running = true; this.simulation.alpha(warm ? .3 : .22).restart();
    }
    dragStart(id) {
        if (!this.byId?.has(id)) return;
        // 새 노드 확장을 위해 임시 고정한 기존 노드는 실제 드래그 때 해제한다.
        this.nodes.forEach(n => { n.fx = null; n.fy = null; });
        this.started = performance.now(); this.drag(id);
        if (!this.paused && !this.reduced.matches) { this.running = true; this.simulation.alphaTarget(.14).restart(); }
    }
    drag(id) { const n = this.byId?.get(id); if (n) { const p = this.cy.getElementById(id).position(); n.x = n.fx = p.x; n.y = n.fy = p.y; } }
    dragEnd(id) {
        const n = this.byId?.get(id); if (n) { n.fx = null; n.fy = null; }
        if (this.simulation) this.simulation.alphaTarget(0);
        if (this.reduced.matches && !this.paused) this.start();
    }
    setPaused(value) { this.paused = value; if (value) { this.stop(); this.settled(0); } else this.start(); }
    destroy() { this.stop(); this.reduced.removeEventListener('change', this.motionChange); }
};
