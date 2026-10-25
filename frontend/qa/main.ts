import { completedId, decision, document, edges, evidence, jobId, makeJob, nodes, review, sourceHash, stats } from "./fixtures";

const params = new URLSearchParams(location.search);
const scenario = params.get("qa") || "normal", role = params.get("role") || "admin";
const target = params.get("target");
const nativeFetch = window.fetch.bind(window);
const job = makeJob(params.get("status") || "NEEDS_USER_INPUT", scenario === "long");
const users = [{ id: "qa-user", role: "admin", daily_limit: 10 }, { id: "qa-team-member-with-a-long-identifier-for-layout", role: "user", daily_limit: 5 }];
const packet = { rows: [decision], total: 1, next_offset: null, project_id: "project" };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });

// 모든 API는 이 검증 진입점 안에서만 가로챈다. 알 수 없는 요청도 외부에 보내지 않는다.
window.fetch = async (input, init) => {
  const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, location.origin);
  if (target === "licenses" && url.pathname.endsWith("third-party-licenses.json")) {
    if (scenario === "error") return json({}, 503);
    if (scenario === "loading") return new Promise<Response>(() => {});
  }
  if (!url.pathname.startsWith("/api/")) return nativeFetch(input, init);
  const path = url.pathname;
  if (scenario === "auth-loading") return new Promise(() => {});
  if (path === "/api/auth/info") return json({ public: true, login_available: scenario !== "unavailable" });
  if (path === "/api/me") return role === "guest" ? json({ error: "" }, 401) : json({ id: "qa-user", role });
  if (path === "/api/me/usage") return json({ runs: 2, remaining_runs: 8 });
  if (path === "/api/service/status") return scenario === "service-error" ? json({ error: "연결 확인 실패" }, 503) : json({ ready: scenario !== "busy", active_count: scenario === "busy" ? 1 : 0, queued_count: 0, max_parallel: 1, own_active_count: 0 });
  const affected = !target || path.includes(target);
  if (scenario === "loading" && affected) return new Promise<Response>((_resolve, reject) => init?.signal?.addEventListener("abort", () => reject(new DOMException("취소", "AbortError"))));
  if (scenario === "error" && affected) return json({ error: "검증용 조회 실패입니다. 다시 시도해주세요." }, 503);
  const empty = scenario === "empty" && affected;
  if (path.includes("/cleanup/preview")) return json({ id: "preview", scope: JSON.parse(String(init?.body || "{}")).scope, counts: { jobs: JSON.parse(String(init?.body || "{}")).scope === "projects" ? 0 : 2, files: 4, project_decisions: 1 }, targets: [jobId], skipped: [], external_references: 1 });
  if (path.includes("/cleanup/execute")) return json({ state: "completed" });
  if (path.includes("/cleanup/catalog")) return json({ jobs: empty ? [] : Array.from({ length: scenario === "long" ? 32 : 3 }, (_, i) => ({ ...job, id: i ? `sample-${i}` : jobId, status: ["FINALIZED", "error", "NEEDS_USER_INPUT"][i % 3] })), pending: [] });
  if (path === "/api/admin/job") return json(job);
  if (path === "/api/admin/overview") return json({ users: empty ? [] : users, executions: empty ? [] : [{ execution_id: "execution", job_id: jobId, kind: "generate", phase: "running" }], embedding_status: "임베딩 오류 없음" });
  if (path.includes("/usage/rows")) return json({ rows: empty ? [] : Array.from({ length: scenario === "long" ? 25 : 3 }, (_, i) => ({ ...stats, id: `call-${i}`, user_id: users[i % 2].id, job_id: jobId, request: job.request, model: "example-model", state: i === 1 ? "uncertain" : "settled", settlement_source: "calculated", cost_evidence: "complete", created_at: job.created_at })), total: empty ? 0 : 30 });
  if (path === "/api/admin/usage") return json({ start: "2026-10-19", end: "2026-10-25", summary: stats, daily: [{ day: "2026-10-24", ...stats }], today: { day: "2026-10-25", spent: "0.125", outstanding: "0.3", limit: "10" }, users });
  if (path.endsWith("/projects")) return json(init?.method === "POST" ? { id: "created", name: "새 프로젝트" } : empty ? [] : [{ id: "project", name: "팀 기록 서비스", node_count: 3, job_count: 1 }, { id: "empty-project", name: "빈 프로젝트", node_count: 0, job_count: 0 }]);
  if (path.includes("/decisions") || path.includes("decision-candidates")) return json({ ...packet, rows: empty ? [] : packet.rows });
  if (path.includes("reused-decisions")) return json(packet);
  if (path.includes("requirement-review")) return json(empty ? { ...review, rows: [], total: 0 } : url.searchParams.has("evidence_for") ? { ...review, rows: [], evidence: [evidence] } : review);
  if (path.includes("implementation-package") && empty) return json(null);
  if (path.includes("package") && !path.endsWith(".zip")) return json({ completed_id: completedId, bundle_id: "b".repeat(64), filename: "approved.zip", available: !empty, completeness: "complete", korean_included: true, task_count: 3, total_size: 1200, source_hash: sourceHash, files: [{ name: "SPEC.en.md", size: 700, sha256: sourceHash }, { name: "SPEC.ko.md", size: 500, sha256: sourceHash }], limitations: [] });
  if (path.endsWith("/document") && init?.method === "POST") return json({ content: document, filename: "spec.ko.md", language: "ko", source_hash: sourceHash });
  if (path === "/api/commands") return json(job);
  if (path === "/api/jobs" || path === "/api/admin/jobs") return json(empty ? [] : [job]);
  if (path === `/api/jobs/${jobId}`) return json(job);
  if (path.endsWith("/steps/research")) return json({ research: { mode: "auto", performed: true, outcome: "links_found", reason: "search_results", query: "PostgreSQL row security", retrieved_at: job.created_at, result_count: 1, sources: [{ title: "PostgreSQL documentation", url: "https://www.postgresql.org/docs/" }] } });
  if (path.includes("/steps/") || path.includes("/completed/")) return json({ document: { content: document, filename: "spec.en.md", source_hash: sourceHash, kind: path.includes("approved") ? "final" : "candidate", completed_id: completedId }, result: { research: { mode: "auto", performed: true, outcome: "links_found", reason: "search_results", query: "PostgreSQL row security", retrieved_at: job.created_at, result_count: 1, sources: [{ title: "PostgreSQL documentation", url: "https://www.postgresql.org/docs/" }] } }, change_review: { status: "complete", after_hash: sourceHash, analysed: 1, remaining: 0, sources: [], changes: [{ id: "change", change: "added", before: null, after: { item_id: "REQ-002", section: "요구사항", text: "보고서 30일 보관", line: 6, start: 0, end: 10, requirement_ids: ["REQ-002"], decision_ids: [] }, status: "analysed", meaning: "semantic", relation: "direct", summary: "보관 정책 추가", rationale: "사용자 답변을 반영했습니다." }] } });
  if (path.endsWith("/graph")) return json({ nodes: empty ? [] : nodes, edges: empty ? [] : edges });
  if (path.endsWith("/search")) return json({ nodes: empty ? [] : nodes });
  if (path.endsWith("/node")) return json({ ...(nodes.find(n => n.id === url.searchParams.get("node_id")) || nodes[0]), edges, document, document_has_more: false });
  if (path.includes("/impact")) {
    const basis = { id: "basis", job_id: jobId, source_hash: sourceHash, node_id: "req", status: "PASS_PENDING_USER_APPROVAL" };
    const spec = { ...nodes[1], section: "Architecture", requirement_id: "" };
    if (init?.method === "POST") return json({ id: "impact", status: "complete", stale: false, basis, proposal: "오프라인 지원", change_kind: "modify", coverage: { total: 3, included: 3, omitted: 0, truncated: 0, recorded_total: 1, recorded_included: 1 }, inferred: [{ topic: "로컬 저장", effect: "저장 정책을 확인해야 합니다.", rationale: "오프라인에서도 기록을 조회합니다.", question: "동기화가 필요한가요?", evidence: [{ node_id: "spec-node", quote: spec.body }] }], limitations: ["제공된 문맥 안의 검토 제안입니다."], sources: [{ node_id: "spec-node", kind: "spec", text: spec.body, section: "Architecture" }] });
    return json({ basis, node: nodes[0], recorded: [{ target: spec, paths: [{ kind: "direct", nodes: [nodes[0], spec] }] }], total: empty ? 0 : 1, offset: 0, has_more: false, next_offset: 20, message: "기록된 연결은 영향 확정을 뜻하지 않습니다." });
  }
  if (init?.method === "POST" && ["/api/logout", "/api/admin/user", "/api/admin/stop", "/api/knowledge/retry", "/api/admin/settings", "/api/admin/settle"].includes(path)) return json({ ok: true });
  return json({ error: `검증 응답이 정의되지 않았습니다: ${path}` }, 404);
};

// 실제 서버 연결 없이 기존 세션 훅의 연결 상태만 재현한다.
class PreviewSocket extends EventTarget {
  onopen: (() => void) | null = null; onclose: (() => void) | null = null; onerror = null; onmessage = null;
  constructor() { super(); queueMicrotask(() => this.onopen?.()); }
  close() {} send() {}
}
window.WebSocket = PreviewSocket as unknown as typeof WebSocket;
await import("../src/main");
