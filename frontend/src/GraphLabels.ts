import type cytoscape from "cytoscape";

export interface LabelBox {
  id: string;
  text: string;
  x: number;
  y: number;
  w: number;
  h: number;
  priority: "selected" | "hover" | "search" | "normal";
}
export interface LabelViewport {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

// 확대해도 글자 크기를 유지하면서 화면 좌표에서 충돌을 피한다.
export class GraphLabels {
  selected = "";
  hover = "";
  matches = new Set<string>();
  amount = 8;
  detail = false;
  private frame: number | null = null;
  private disposed = false;
  private measure = document.createElement("canvas").getContext("2d");

  constructor(
    private cy: cytoscape.Core,
    private viewport: () => LabelViewport,
    private changed: (labels: LabelBox[]) => void,
  ) {
    if (this.measure)
      this.measure.font = '14px "Segoe UI", "Malgun Gothic", sans-serif';
  }

  schedule = () => {
    if (this.disposed || this.frame !== null) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = null;
      this.paint();
    });
  };

  private paint() {
    if (this.disposed || this.cy.destroyed()) return;
    const cy = this.cy,
      area = this.viewport(),
      occupied: LabelBox[] = [];
    const priority = (node: cytoscape.NodeSingular): LabelBox["priority"] =>
      node.id() === this.selected
        ? "selected"
        : node.id() === this.hover
          ? "hover"
          : (node.data("members") || []).some((id: string) =>
                this.matches.has(id),
              )
            ? "search"
            : "normal";
    const rank = (node: cytoscape.NodeSingular) => {
      const p = priority(node);
      return p === "selected"
        ? 1e9
        : p === "hover"
          ? 1e8
          : p === "search"
            ? 1e7
            : Number(node.data("degree") || 0);
    };
    const candidates = cy
      .nodes()
      .toArray()
      .sort((a, b) => rank(b) - rank(a) || a.id().localeCompare(b.id()));
    const budget = Math.min(
      this.amount,
      this.detail && cy.zoom() >= 1.15 ? 20 : 8,
    );
    const intersects = (a: LabelBox, b: LabelBox) =>
      a.x < b.x + b.w + 5 &&
      a.x + a.w + 5 > b.x &&
      a.y < b.y + b.h + 4 &&
      a.y + a.h + 4 > b.y;
    const width = (text: string) =>
      this.measure?.measureText(text).width ?? text.length * 14;
    for (const node of candidates) {
      if (occupied.length >= budget) break;
      const point = node.renderedPosition(),
        p = priority(node);
      if (
        point.x < 0 ||
        point.x > cy.width() ||
        point.y < 0 ||
        point.y > cy.height()
      )
        continue;
      const maxWidth = Math.min(216, area.right - area.left - 8);
      if (maxWidth < 28) continue;
      let text = String(node.data("label") || "");
      while (text.length > 2 && width(text) > maxWidth - 12)
        text = text.slice(0, -2) + "…";
      const w = Math.ceil(width(text)) + 12,
        h = 26;
      const common = { id: node.id(), text, w, h, priority: p };
      const places: LabelBox[] = [
        { ...common, x: point.x - w / 2, y: point.y + 14 },
        { ...common, x: point.x + 16, y: point.y - h / 2 },
        { ...common, x: point.x - w - 16, y: point.y - h / 2 },
        { ...common, x: point.x - w / 2, y: point.y - h - 14 },
      ];
      const fits = (box: LabelBox) =>
        box.x >= area.left &&
        box.x + box.w <= area.right &&
        box.y >= area.top &&
        box.y + box.h <= area.bottom &&
        !occupied.some((other) => intersects(box, other));
      let box = places.find(fits);
      if (!box && (p === "selected" || p === "hover")) {
        const clamped = {
          ...places[0],
          x: Math.max(area.left, Math.min(area.right - w, places[0].x)),
          y: Math.max(area.top, Math.min(area.bottom - h, places[0].y)),
        };
        if (fits(clamped)) box = clamped;
      }
      if (box) occupied.push(box);
    }
    this.changed(occupied);
  }

  destroy() {
    this.disposed = true;
    if (this.frame !== null) cancelAnimationFrame(this.frame);
    this.frame = null;
  }
}
