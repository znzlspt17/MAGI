export type KnowledgeNode = {
  id: string;
  kind: string;
  body: string;
  job_id?: string;
  logical_key?: string;
  active?: boolean;
  attrs?: Record<string, any>;
  matches?: { quote: string }[];
  [key: string]: any;
};
export type KnowledgeEdge = {
  id?: string;
  source: string;
  target: string;
  kind: string;
  [key: string]: any;
};
export type KnowledgeGraph = {
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
  has_more?: boolean;
};
export const kinds: Record<string, string> = {
  input: "사용자 입력",
  decision: "결정",
  requirement: "요구사항",
  spec: "명세",
  review: "검토",
};
export const colors: Record<string, string> = {
  input: "#aa752f",
  decision: "#8860b6",
  requirement: "#397f96",
  spec: "#36876b",
  review: "#ac587a",
};
export const edgeLabels: Record<string, string> = {
  evidence: "근거",
  derived: "도출",
  implemented: "반영",
  reviewed: "검토",
  superseded: "대체",
  reused: "재사용",
};
const sections: Record<string, string> = {
  architecture: "아키텍처",
  test_plan: "테스트 계획",
  manual_verification_checklist: "수동 검증",
  acceptance_criteria: "수용 기준",
  instructions_for_ai_coding_agent: "구현 지침",
  implementation_order: "구현 순서",
  persistence_artifact_policy: "저장 정책",
  configuration_policy: "설정 정책",
  error_handling_policy: "오류 처리",
  data_flow: "데이터 흐름",
  module_responsibilities: "모듈 책임",
  output_contract: "출력 규약",
  input_contract: "입력 규약",
  forbidden_behaviors: "금지 동작",
  evidence_summary: "근거 요약",
  definitions: "용어 정의",
  in_scope: "포함 범위",
  user_intent: "사용자 의도",
  background: "배경",
  mission: "목표",
};
export function title(node: KnowledgeNode) {
  const a = node.attrs || {};
  if (a.requirement_id) return a.requirement_id;
  if (node.logical_key === "user_request") return "원래 요청";
  if (node.logical_key === "user_feedback") return "수정 의견";
  if (node.kind === "input" && a.question) return a.question.slice(0, 25);
  if (node.kind === "spec" && a.section) {
    const section =
      sections[a.section] ||
      a.section.replace(/^#+\s*\d*\.?\s*/, "").slice(0, 25);
    return (
      section +
      (node.logical_key?.startsWith("item:")
        ? " · " + node.logical_key.slice(5)
        : "")
    );
  }
  return (
    (node.body || "")
      .replace(/^\s*(?:Assumption\s*:?|가정\s*:?)\s*/i, "")
      .replace(/\s+/g, " ")
      .slice(0, 27) ||
    kinds[node.kind] ||
    "지식"
  );
}
export function build(
  graph: KnowledgeGraph,
  { mode = "summary", expanded = new Set<string>(), showOrphans = false } = {},
) {
  const originals = new Map(graph.nodes.map((n) => [n.id, n])),
    degree = new Map(graph.nodes.map((n) => [n.id, 0]));
  const edges = graph.edges.filter(
    (e) => originals.has(e.source) && originals.has(e.target),
  );
  for (const e of edges) {
    degree.set(e.source, degree.get(e.source)! + 1);
    degree.set(e.target, degree.get(e.target)! + 1);
  }
  const orphans = graph.nodes.filter((n) => !degree.get(n.id)),
    nodes = new Map<string, any>(),
    aliases = new Map<string, string>();
  for (const n of graph.nodes) {
    if (!showOrphans && !degree.get(n.id)) continue;
    const a = n.attrs || {};
    const group =
      n.kind === "spec" && a.artifact_hash && n.job_id
        ? "group:" +
          JSON.stringify([n.job_id, a.artifact_path || "", a.artifact_hash])
        : null;
    const id =
      mode === "summary" && group && !expanded.has(group) ? group : n.id;
    aliases.set(n.id, id);
    if (!nodes.has(id))
      nodes.set(id, {
        id,
        kind: n.kind,
        color: colors[n.kind] || "#8491a5",
        label: title(n),
        members: [],
        virtual: id === group,
        active: n.active,
        degree: 0,
      });
    const d = nodes.get(id);
    d.members.push(n.id);
    if (d.virtual) d.label = `명세 · ${d.members.length}개`;
  }
  const links = new Map<string, any>();
  let internalEdges = 0;
  for (const e of edges) {
    const source = aliases.get(e.source),
      target = aliases.get(e.target);
    if (!source || !target) continue;
    if (source === target) {
      internalEdges++;
      continue;
    }
    const id = "link:" + JSON.stringify([source, target, e.kind]);
    if (!links.has(id))
      links.set(id, {
        id,
        source,
        target,
        kind: e.kind,
        count: 0,
        members: [],
      });
    const d = links.get(id);
    d.count++;
    d.members.push(e.id);
  }
  for (const e of links.values()) {
    nodes.get(e.source).degree += e.count;
    nodes.get(e.target).degree += e.count;
  }
  return {
    nodes: [...nodes.values()],
    edges: [...links.values()],
    originals,
    aliases,
    orphans,
    rawCount: graph.nodes.length,
    rawEdges: edges.length,
    internalEdges,
    has_more: !!graph.has_more,
  };
}
