import { useEffect, useRef, useState } from "react";
import cytoscape from "cytoscape";
import {
  forceSimulation,
  forceManyBody,
  forceLink,
  forceCollide,
  forceX,
  forceY,
} from "d3-force";
import { build, edgeLabels } from "./graph-data";
import { GraphLabels, type LabelBox } from "./GraphLabels";
export type GraphHandle = {
  zoom: (factor: number) => void;
  fit: () => void;
  layout: () => void;
};
export default function Graph({
  display,
  selected,
  matches,
  spacing,
  distance,
  labels,
  paused,
  detail = false,
  onSelect,
  onClear,
  onRelation,
  handle,
}: {
  display: ReturnType<typeof build>;
  selected: string;
  matches: string[];
  spacing: number;
  distance: number;
  labels: number;
  paused: boolean;
  detail?: boolean;
  onSelect: (node: any) => void;
  onClear: () => void;
  onRelation: (text: string) => void;
  handle: React.MutableRefObject<GraphHandle | null>;
}) {
  const host = useRef<HTMLDivElement>(null),
    cyRef = useRef<cytoscape.Core | null>(null),
    simulation = useRef<any>(null),
    callbacks = useRef({ onSelect, onClear, onRelation }),
    pausedRef = useRef(paused);
  callbacks.current = { onSelect, onClear, onRelation };
  pausedRef.current = paused;
  const [epoch, setEpoch] = useState(0),
    [placedLabels, setPlacedLabels] = useState<LabelBox[]>([]),
    labelController = useRef<GraphLabels | null>(null);
  useEffect(() => {
    labelController.current?.schedule();
  }, [onSelect, onClear, onRelation]);
  useEffect(() => {
    if (!host.current) return;
    const cy = cytoscape({
      container: host.current,
      elements: [],
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)",
            label: "",
            width: 25,
            height: 25,
            "font-size": 14,
            "text-valign": "bottom",
            "text-margin-y": 8,
            color: "#374151",
            "text-background-color": "#fff",
            "text-background-opacity": 0.8,
            "text-background-padding": "3px",
          },
        },
        {
          selector: "node[?virtual]",
          style: { shape: "round-rectangle", width: 48, height: 34 },
        },
        {
          selector: "edge",
          style: {
            width: 1.4,
            "line-color": "#bdc9d5",
            "target-arrow-color": "#9caebf",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
          },
        },
        {
          selector: "node.neighbor",
          style: { "border-width": 2, "border-color": "#8ba7c6" },
        },
        {
          selector: "edge.neighbor",
          style: {
            "line-color": "#4276a8",
            "target-arrow-color": "#4276a8",
            width: 2.5,
          },
        },
        {
          selector: ".chosen",
          style: { "border-width": 4, "border-color": "#173d73" },
        },
        {
          selector: ".match",
          style: { "border-width": 3, "border-color": "#d59723" },
        },
        { selector: ".hide-label", style: { label: "" } },
      ],
      minZoom: 0.15,
      maxZoom: 4,
    });
    cyRef.current = cy;
    const labelsLayer = new GraphLabels(
      cy,
      () => {
        const workspace = host.current?.parentElement,
          base = host.current!.getBoundingClientRect(),
          left = workspace
            ?.querySelector("#knowledge-list")
            ?.getBoundingClientRect(),
          right = workspace
            ?.querySelector("#graph-inspector")
            ?.getBoundingClientRect();
        return {
          left: left ? left.right - base.left + 12 : 16,
          top: 16,
          right: right ? right.left - base.left - 12 : cy.width() - 16,
          bottom: cy.height() - 16,
        };
      },
      setPlacedLabels,
    );
    labelController.current = labelsLayer;
    cy.on("position pan zoom resize add remove", labelsLayer.schedule);
    cy.on("mouseover", "node", (e) => {
      labelsLayer.hover = e.target.id();
      labelsLayer.schedule();
    });
    cy.on("mouseout", "node", () => {
      labelsLayer.hover = "";
      labelsLayer.schedule();
    });
    cy.on("tap", "node", (e) => callbacks.current.onSelect(e.target.data()));
    cy.on("tap", "edge", (e) => {
      const d = e.target.data();
      callbacks.current.onRelation(
        `${e.target.source().data("label")} → ${edgeLabels[d.kind] || d.kind} → ${e.target.target().data("label")} · ${d.count}개 실제 관계`,
      );
    });
    cy.on("tap", (e) => {
      if (e.target === cy) callbacks.current.onClear();
    });
    cy.on("drag", "node", (e) => {
      const p = e.target.position(),
        n = simulation.current
          ?.nodes()
          .find((n: any) => n.id === e.target.id());
      if (n) {
        n.x = p.x;
        n.y = p.y;
        n.fx = p.x;
        n.fy = p.y;
      }
    });
    cy.on("free", "node", (e) => {
      const n = simulation.current
        ?.nodes()
        .find((n: any) => n.id === e.target.id());
      if (n) {
        n.fx = null;
        n.fy = null;
      }
    });
    const observer = new ResizeObserver(() => {
      if (!cy.destroyed()) cy.resize();
    });
    observer.observe(host.current);
    const stop = () => simulation.current?.stop();
    const motion = matchMedia("(prefers-reduced-motion: reduce)");
    const visibility = () => {
      if (document.hidden || motion.matches) stop();
      else if (!pausedRef.current) simulation.current?.restart();
    };
    const hide = () => {
      stop();
      observer.disconnect();
      labelsLayer.destroy();
      labelController.current = null;
      setPlacedLabels([]);
      cy.destroy();
      cyRef.current = null;
      handle.current = null;
    };
    const show = (event: PageTransitionEvent) => {
      if (event.persisted) setEpoch((v) => v + 1);
    };
    document.addEventListener("visibilitychange", visibility);
    motion.addEventListener("change", visibility);
    window.addEventListener("pagehide", hide);
    window.addEventListener("pageshow", show);
    return () => {
      stop();
      observer.disconnect();
      labelsLayer.destroy();
      labelController.current = null;
      document.removeEventListener("visibilitychange", visibility);
      motion.removeEventListener("change", visibility);
      window.removeEventListener("pagehide", hide);
      window.removeEventListener("pageshow", show);
      if (!cy.destroyed()) cy.destroy();
      cyRef.current = null;
      handle.current = null;
    };
  }, [epoch]);
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    simulation.current?.stop();
    const prior = new Map(cy.nodes().map((n) => [n.id(), n.position()]));
    cy.elements().remove();
    cy.add([
      ...display.nodes.map((n, i) => ({
        data: n,
        position: prior.get(n.id) || {
          x: Math.cos(i * 2.4) * Math.sqrt(i + 1) * 38,
          y: Math.sin(i * 2.4) * Math.sqrt(i + 1) * 38,
        },
      })),
      ...display.edges.map((e) => ({ data: e })),
    ]);
    const nodes = cy.nodes().map((n) => ({ id: n.id(), ...n.position() })),
      links = display.edges.map((e) => ({
        source: e.source,
        target: e.target,
      }));
    const sim = forceSimulation<any>(nodes)
      .stop()
      .force("charge", forceManyBody().strength(-230).distanceMax(900))
      .force(
        "link",
        forceLink<any, any>(links)
          .id((n: any) => n.id)
          .distance(distance)
          .strength(0.18),
      )
      .force("collide", forceCollide(spacing).iterations(2))
      .force("x", forceX(0).strength(0.025))
      .force("y", forceY(0).strength(0.025))
      .velocityDecay(0.5)
      .alphaDecay(0.075)
      .alphaMin(0.005);
    simulation.current = sim;
    const paint = () =>
      cy.batch(() =>
        nodes.forEach((n) => {
          const item = cy.getElementById(n.id);
          if (!item.grabbed()) item.position({ x: n.x || 0, y: n.y || 0 });
        }),
      );
    sim.on("tick", paint).on("end", () => cy.fit(undefined, 48));
    const run = () => {
      if (pausedRef.current || document.hidden) return;
      if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
        sim.tick(100);
        paint();
        cy.fit(undefined, 48);
      } else sim.alpha(0.5).restart();
    };
    sim.tick(35);
    paint();
    cy.fit(undefined, 48);
    run();
    handle.current = {
      zoom: (f) =>
        cy.zoom({
          level: cy.zoom() * f,
          renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 },
        }),
      fit: () => cy.fit(undefined, 48),
      layout: run,
    };
    return () => {
      sim.stop();
    };
  }, [display, spacing, distance, epoch]);
  useEffect(() => {
    if (paused || matchMedia("(prefers-reduced-motion: reduce)").matches)
      simulation.current?.stop();
    else if (!document.hidden) simulation.current?.alpha(0.25).restart();
  }, [paused]);
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().removeClass("chosen match hide-label neighbor");
    const id = display.aliases.get(selected) || selected;
    const node = cy.getElementById(id);
    node.addClass("chosen");
    node.neighborhood().addClass("neighbor");
    for (const item of matches)
      cy.getElementById(display.aliases.get(item) || item).addClass("match");
    const overlay = labelController.current;
    if (overlay) {
      overlay.selected = id;
      overlay.matches = new Set(matches);
      overlay.amount = labels;
      overlay.detail = detail;
      overlay.schedule();
    }
  }, [display, selected, matches, labels, detail, epoch]);
  return (
    <>
      <div
        ref={host}
        id="knowledge-graph"
        tabIndex={0}
        role="region"
        aria-label="지식 관계도. 항목 목록으로도 탐색할 수 있습니다."
        onKeyDown={(e) => {
          if (e.key === "Escape") onClear();
          if (e.key === "+" || e.key === "=") handle.current?.zoom(1.2);
          if (e.key === "-") handle.current?.zoom(1 / 1.2);
          if (e.key === "Home") handle.current?.fit();
        }}
      />
      <div id="graph-labels" className="react-graph-labels" aria-hidden="true">
        {placedLabels.map((label) => (
          <span
            key={label.id}
            className={
              "graph-node-label" +
              (label.priority === "selected" ? " selected" : "")
            }
            data-node-id={label.id}
            data-priority={label.priority}
            style={{
              left: label.x,
              top: label.y,
              width: label.w,
              height: label.h,
            }}
          >
            {label.text}
          </span>
        ))}
      </div>
    </>
  );
}
