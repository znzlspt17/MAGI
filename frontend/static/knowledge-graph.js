/* Cytoscape는 그리기·입력만, 물리 배치와 라벨은 별도 모듈이 담당한다. */
window.MagiKnowledgeGraph = class {
    constructor(container, callbacks) {
        this.container = container; this.callbacks = callbacks;
        this.mode = 'summary'; this.expanded = new Set(); this.showOrphans = true; this.matches = new Set();
        this.raw = {nodes: [], edges: []}; this.touched = false;
        this.cy = cytoscape({container, layout: {name: 'preset'}, elements: [], minZoom: .08, maxZoom: 4, wheelSensitivity: .25,
            style: [
                {selector: 'node', style: {'background-color': 'data(color)', width: 12, height: 12, label: '', 'border-width': 1.5, 'border-color': '#fcfcfe'}},
                {selector: 'edge', style: {width: .8, 'line-color': '#a3b0c1', opacity: .45, 'curve-style': 'bezier', 'target-arrow-shape': 'none'}},
                {selector: 'node.virtual', style: {'border-color': '#d4e9e2', 'border-width': 3}},
                {selector: 'node.inactive', style: {'border-style': 'dashed', 'border-color': '#79869b'}},
                {selector: 'node.muted', style: {opacity: .65}},
                {selector: 'node.match', style: {'border-color': '#d4a64c'}},
                {selector: 'node:selected', style: {'border-color': '#67508e'}},
                {selector: 'edge.neighbor, edge:selected', style: {'line-color': '#8a75ac', 'target-arrow-color': '#8a75ac', 'target-arrow-shape': 'triangle', opacity: .9}}
            ]});
        this.labels = new MagiGraphLabels(this.cy, document.getElementById('graph-labels'), () => callbacks.viewport());
        this.layout = new MagiGraphLayout(this.cy, () => this.labels.schedule(), ms => {
            if (this.autoFit && !this.touched) this.fit();
            this.autoFit = false; container.dataset.layoutMs = String(ms); container.dataset.settled = 'true'; this.labels.schedule();
        });
        this.cy.on('tap', 'node', event => {
            this.touched = true; this.select(event.target.id());
            callbacks.select(this.display.nodes.find(n => n.id === event.target.id()));
        });
        this.cy.on('mouseover', 'node', e => { this.labels.hover = e.target.id(); this.highlight(e.target.id()); });
        this.cy.on('mouseout', 'node', () => { this.labels.hover = null; this.highlight(this.cy.$('node:selected').id()); });
        this.cy.on('tap', 'edge', event => callbacks.edge(event.target.data()));
        this.cy.on('mouseover', 'edge', event => { event.target.addClass('neighbor'); this.updateSizes(); callbacks.edge(event.target.data()); });
        this.cy.on('mouseout', 'edge', () => this.highlight(this.cy.$('node:selected').id()));
        this.cy.on('tap', event => { if (event.target === this.cy) this.clear(); });
        this.cy.on('grab', 'node', e => { this.touched = true; this.autoFit = false; this.container.dataset.settled = 'false'; this.layout.dragStart(e.target.id()); });
        this.cy.on('drag', 'node', e => { this.layout.drag(e.target.id()); this.labels.schedule(); });
        this.cy.on('free', 'node', e => this.layout.dragEnd(e.target.id()));
        this.cy.on('pan zoom', () => { this.updateSizes(); this.labels.schedule(); });
        this.cy.on('dragpan scrollzoom pinchzoom', () => { this.touched = true; this.autoFit = false; });
        this.keydown = event => {
            if (event.key === 'Escape') { this.clear(); return; }
            const shifts = {ArrowLeft: [40, 0], ArrowRight: [-40, 0], ArrowUp: [0, 40], ArrowDown: [0, -40]};
            if (shifts[event.key]) { event.preventDefault(); const [x, y] = shifts[event.key]; this.cy.panBy({x, y}); }
            else if (['+', '=', '-'].includes(event.key)) { event.preventDefault(); this.zoom(event.key === '-' ? 1 / 1.2 : 1.2); }
        };
        container.addEventListener('keydown', this.keydown);
    }
    render(graph, {merge = false, centerId = null} = {}) {
        this.raw = graph; this.layout.stop(); this.labels.hover = null;
        const previous = new Map(this.cy.nodes().map(n => [n.id(), {...n.position()}]));
        const anchor = previous.get(this.display?.aliases.get(centerId)) || {x: 0, y: 0};
        this.display = MagiGraphData.build(graph, {mode: this.mode, expanded: this.expanded, showOrphans: this.showOrphans});
        const oldSelected = this.cy.$('node:selected').id(); let index = 0;
        this.cy.batch(() => {
            this.cy.elements().remove();
            for (const node of this.display.nodes) {
                const angle = index++ * 2.39996, radius = 35 + 20 * Math.sqrt(index);
                const position = previous.get(node.id) || {x: anchor.x + Math.cos(angle) * radius, y: anchor.y + Math.sin(angle) * radius};
                this.cy.add({data: node, position, classes: [node.virtual ? 'virtual' : '', node.active ? '' : 'inactive'].join(' ')});
            }
            this.cy.add(this.display.edges.map(edge => ({data: edge})));
        });
        if (oldSelected && this.cy.getElementById(oldSelected).length) this.cy.getElementById(oldSelected).select();
        this.applyMatches(); this.highlight(this.cy.$('node:selected').id()); this.updateSizes();
        this.touched = false; this.autoFit = !merge;
        delete this.container.dataset.layoutMs; this.container.dataset.settled = 'false';
        const fixed = merge ? new Set(previous.keys()) : new Set();
        this.layout.start({fixed, warm: !merge});
        if (!merge && !this.layout.reduced.matches) this.fit();
        this.callbacks.stats(this.display);
    }
    updateSizes() {
        const z = this.cy.zoom();
        this.cy.batch(() => {
            this.cy.nodes().forEach(n => {
                const diameter = n.selected() ? 18 : Math.min(16, 8 + Math.sqrt(n.data('degree') || 0));
                n.style({width: diameter / z, height: diameter / z, 'border-width': (n.selected() || n.hasClass('match') ? 2 : n.data('virtual') ? 2.5 : 1) / z});
            });
            this.cy.edges().forEach(e => e.style({width: (e.hasClass('neighbor') || e.selected() ? 1.3 : .8) / z, 'arrow-scale': .6 / z}));
        });
    }
    select(id) {
        const displayId = this.display.aliases.get(id) || id;
        this.cy.nodes().unselect(); this.cy.getElementById(displayId).select(); this.highlight(displayId);
    }
    highlight(id) {
        this.cy.elements().removeClass('muted neighbor');
        if (id && this.cy.getElementById(id).length) {
            const node = this.cy.getElementById(id), neighbors = node.closedNeighborhood();
            this.cy.nodes().difference(neighbors).addClass('muted'); neighbors.addClass('neighbor');
        }
        this.updateSizes(); this.labels.schedule();
    }
    clear() { this.cy.elements().unselect(); this.highlight(null); this.callbacks.clear(); }
    applyMatches() {
        this.cy.nodes().forEach(n => n.toggleClass('match', n.data('members').some(id => this.matches.has(id))));
        this.labels.matches = this.matches; this.updateSizes(); this.labels.schedule();
    }
    setMatches(ids) { this.matches = new Set(ids); this.applyMatches(); }
    fit() { if (this.cy.nodes().length) this.cy.fit(undefined, 78); this.updateSizes(); this.labels.schedule(); }
    zoom(factor) {
        this.touched = true; this.autoFit = false;
        this.cy.zoom({level: Math.max(this.cy.minZoom(), Math.min(this.cy.maxZoom(), this.cy.zoom() * factor)), renderedPosition: {x: this.cy.width() / 2, y: this.cy.height() / 2}});
    }
    resize() { this.cy.resize(); this.labels.schedule(); }
    destroy() { this.layout.destroy(); this.labels.destroy(); this.container.removeEventListener('keydown', this.keydown); this.cy.destroy(); }
};
