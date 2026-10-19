/* 라벨은 화면 좌표에서 배치하여 확대 비율과 관계없이 겹침을 피한다. */
window.MagiGraphLabels = class {
    constructor(cy, layer, viewport) {
        this.cy = cy; this.layer = layer; this.viewport = viewport; this.matches = new Set(); this.amount = 8;
        this.measure = document.createElement('canvas').getContext('2d'); this.measure.font = '12px "Segoe UI", "Malgun Gothic", sans-serif';
    }
    schedule() { if (!this.frame) this.frame = requestAnimationFrame(() => { this.frame = null; this.paint(); }); }
    paint() {
        const cy = this.cy, area = this.viewport(), occupied = [], fragments = document.createDocumentFragment();
        const selected = cy.$('node:selected').id(), hover = this.hover;
        const rank = node => node.id() === selected ? 1e9 : node.id() === hover ? 1e8 : node.data('members').some(id => this.matches.has(id)) ? 1e7 : node.data('degree');
        const candidates = cy.nodes().toArray().sort((a, b) => rank(b) - rank(a) || a.id().localeCompare(b.id()));
        const budget = Math.min(this.amount, this.detail && cy.zoom() >= 1.15 ? 20 : 8);
        const intersects = (a, b) => a.x < b.x + b.w + 5 && a.x + a.w + 5 > b.x && a.y < b.y + b.h + 4 && a.y + a.h + 4 > b.y;
        for (const node of candidates) {
            if (occupied.length >= budget) break;
            const point = node.renderedPosition(), priority = node.id() === selected || node.id() === hover;
            if (point.x < 0 || point.x > cy.width() || point.y < 0 || point.y > cy.height()) continue;
            let text = node.data('label');
            const maxWidth = Math.min(196, area.right - area.left - 8);
            if (maxWidth < 24) continue;
            while (text.length > 2 && this.measure.measureText(text).width > maxWidth - 12) text = text.slice(0, -2) + '…';
            const w = Math.ceil(this.measure.measureText(text).width) + 12, h = 23;
            const places = [
                {x: point.x - w / 2, y: point.y + 12, w, h},
                {x: point.x + 14, y: point.y - h / 2, w, h},
                {x: point.x - w - 14, y: point.y - h / 2, w, h},
                {x: point.x - w / 2, y: point.y - h - 12, w, h}
            ];
            const fits = box => box.x >= area.left && box.x + box.w <= area.right && box.y >= area.top && box.y + box.h <= area.bottom && !occupied.some(other => intersects(box, other));
            let box = places.find(fits);
            if (!box && priority) {
                const clamped = {x: Math.max(area.left, Math.min(area.right - w, places[0].x)), y: Math.max(area.top, Math.min(area.bottom - h, places[0].y)), w, h};
                if (fits(clamped)) box = clamped;
            }
            if (!box) continue;
            occupied.push(box);
            const label = document.createElement('span'); label.className = 'graph-node-label' + (node.id() === selected ? ' selected' : '');
            label.dataset.nodeId = node.id(); label.textContent = text;
            Object.assign(label.style, {left: `${box.x}px`, top: `${box.y}px`, width: `${box.w}px`, height: `${box.h}px`});
            fragments.append(label);
        }
        this.layer.replaceChildren(fragments);
    }
    destroy() { cancelAnimationFrame(this.frame); this.frame = null; this.layer.replaceChildren(); }
};
