import { MagnifyingGlassIcon, GraphIcon, ListBulletsIcon, ArrowsOutIcon, FunnelIcon } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, post, ApiError } from "./api";
import { useAuth } from "./Auth";
import { Markdown } from "./UI";
import KnowledgeGraph, { type GraphHandle } from "./KnowledgeGraph";
import {
  build,
  kinds,
  colors,
  title,
  edgeLabels,
  type KnowledgeGraph as GraphData,
  type KnowledgeNode,
} from "./graph-data";
import "./admin-knowledge.css";
const empty: GraphData = { nodes: [], edges: [] };
const sourceLabel = (source: string) =>
  source.startsWith("user_request")
    ? "원래 요청"
    : source.startsWith("user_feedback")
      ? "수정 의견"
      : source.startsWith("user_answer:")
        ? "사용자 답변 " + source.split(":")[1]
        : source === "system"
          ? "시스템 규칙"
          : source;
export default function Knowledge({
  admin = false,
  onDeleted,
  selectedJobId,
}: {
  admin?: boolean;
  onDeleted?: (ids: string[]) => void;
  selectedJobId?: string;
}) {
  const auth = useAuth(),
    canRetry = !auth.publicMode || auth.user?.role === "admin",
    mutationBusy =
      !!(auth.status.busy && !auth.status.mine) || !!auth.status.recovering;
  const saved = useRef(new URLSearchParams(location.search)),
    [projects, setProjects] = useState<any[]>([]),
    [project, setProject] = useState(
      admin ? saved.current.get("project_id") || "" : "",
    ),
    [sessions, setSessions] = useState<any[]>([]),
    [session, setSession] = useState(
      saved.current.get("job_id") || selectedJobId || "",
    ),
    [query, setQuery] = useState(saved.current.get("query") || ""),
    [kind, setKind] = useState(""),
    [status, setStatus] = useState("");
  const [graph, setGraph] = useState<GraphData>(empty),
    [results, setResults] = useState<KnowledgeNode[] | null>(null),
    [matches, setMatches] = useState<string[]>([]),
    [selected, setSelected] = useState<KnowledgeNode | null>(null),
    [group, setGroup] = useState<any>(null),
    [mode, setMode] = useState("summary"),
    [expanded, setExpanded] = useState(new Set<string>()),
    [orphans, setOrphans] = useState(false),
    [list, setList] = useState(false),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [spacing, setSpacing] = useState(26),
    [distance, setDistance] = useState(95),
    [labels, setLabels] = useState(8),
    [paused, setPaused] = useState(false),
    [relation, setRelation] = useState(
      "끌어서 이동 · 휠로 확대 · Esc 선택 해제",
    ),
    [refresh, setRefresh] = useState(0),
    [focused, setFocused] = useState(false),
    [projectOperation, setProjectOperation] = useState<any>(null);
  const generation = useRef(0),
    selection = useRef(0),
    sessionGeneration = useRef(0),
    handle = useRef<GraphHandle | null>(null),
    active = useRef(true);
  const display = useMemo(
    () => build(graph, { mode, expanded, showOrphans: orphans }),
    [graph, mode, expanded, orphans],
  );
  const fail = (e: any) =>
    setNotice(
      e instanceof ApiError && e.status === 404
        ? "출처가 삭제되었거나 더 이상 존재하지 않습니다. 다시 검색하세요."
        : e.message || "지식 조회에 실패했습니다.",
    );
  function invalidate() {
    generation.current++;
    selection.current++;
    setSelected(null);
    setGroup(null);
    setResults(null);
    setMatches([]);
    setGraph(empty);
    setFocused(false);
  }
  function params() {
    const p = new URLSearchParams();
    if (session) p.set("job_id", session);
    if (kind) p.set("kind", kind);
    if (status) p.set("status", status);
    return p;
  }
  function path(action: string, p = new URLSearchParams()) {
    if (admin) {
      p.set("project_id", project);
      return "/api/admin/" + action + "?" + p;
    }
    return "/api/knowledge/" + action + "?" + p;
  }
  const clear = () => {
    selection.current++;
    setSelected(null);
    setGroup(null);
    setRelation("끌어서 이동 · 휠로 확대 · Esc 선택 해제");
  };
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      generation.current++;
      selection.current++;
      sessionGeneration.current++;
    };
  }, []);
  useEffect(() => {
    if (!admin) return;
    let live = true;
    api<any[]>("/api/admin/projects")
      .then((items) => {
        if (!live) return;
        setProjects(items);
        setProject((p) =>
          items.some((i) => i.id === p) ? p : items[0]?.id || "",
        );
      })
      .catch((e) => live && fail(e));
    return () => {
      live = false;
    };
  }, [admin, refresh]);
  useEffect(() => {
    const ticket = ++sessionGeneration.current;
    if (admin && !project) {
      setSessions([]);
      return;
    }
    api<any[]>(
      admin
        ? "/api/admin/jobs?project_id=" + encodeURIComponent(project)
        : "/api/jobs",
    )
      .then((items) => {
        if (ticket !== sessionGeneration.current || !active.current) return;
        setSessions(items);
        setSession((current) =>
          items.some((i) => i.id === current) ? current : "",
        );
      })
      .catch(
        (e) =>
          ticket === sessionGeneration.current && active.current && fail(e),
      );
    return () => {
      sessionGeneration.current++;
    };
  }, [admin, project, refresh]);
  useEffect(() => {
    if (selectedJobId !== undefined) {
      invalidate();
      setSession(selectedJobId);
    }
  }, [selectedJobId]);
  useEffect(() => {
    const cleanup = () => {
      invalidate();
      setRefresh((r) => r + 1);
    };
    window.addEventListener("cleanup", cleanup);
    return () => window.removeEventListener("cleanup", cleanup);
  }, []);
  useEffect(() => {
    const ticket = ++generation.current;
    selection.current++;
    setSelected(null);
    setGroup(null);
    setNotice("");
    setBusy(true);
    setResults(null);
    setMatches([]);
    setGraph(empty);
    setExpanded(new Set());
    setFocused(false);
    if (admin) {
      const url = new URL(location.href);
      url.searchParams.set("project_id", project);
      url.searchParams.set("job_id", session);
      url.searchParams.set("query", query);
      history.replaceState({}, "", url);
    }
    if (admin && !project) {
      setBusy(false);
      return;
    }
    (async () => {
      try {
        const p = params();
        p.set("depth", "0");
        p.set("limit", "100");
        const data = await api<GraphData>(path("graph", p));
        if (ticket !== generation.current || !active.current) return;
        setGraph(data);
        if (query.trim()) {
          const s = params();
          s.set("query", query.trim());
          const result = await api<{ nodes: KnowledgeNode[] }>(
            path("search", s),
          );
          if (ticket !== generation.current || !active.current) return;
          setResults(result.nodes);
          setMatches(result.nodes.map((n) => n.id));
          setList(true);
        }
      } catch (e) {
        if (ticket === generation.current && active.current) fail(e);
      } finally {
        if (ticket === generation.current && active.current) setBusy(false);
      }
    })();
    return () => {
      generation.current++;
      selection.current++;
    };
  }, [admin, project, session, kind, status, refresh]);
  async function search() {
    setRefresh((r) => r + 1);
  }
  async function expand(id: string, replace = false, depth = 1) {
    const ticket = ++generation.current,
      p = params();
    p.set("node_id", id);
    p.set("depth", String(depth));
    p.set("limit", "100");
    try {
      const data = await api<GraphData>(path("graph", p));
      if (ticket !== generation.current || !active.current) return false;
      setGraph((previous) => {
        if (replace) return data;
        const nodes = new Map(previous.nodes.map((n) => [n.id, n]));
        let more = previous.has_more || data.has_more;
        for (const n of data.nodes) {
          if (nodes.has(n.id) || nodes.size < 100) nodes.set(n.id, n);
          else more = true;
        }
        const edges = new Map(
          [...previous.edges, ...data.edges]
            .filter((e) => nodes.has(e.source) && nodes.has(e.target))
            .map((e) => [
              e.id || JSON.stringify([e.source, e.target, e.kind]),
              e,
            ]),
        );
        return {
          nodes: [...nodes.values()],
          edges: [...edges.values()],
          has_more: more,
        };
      });
      if (replace) {
        setMode("detail");
        setFocused(true);
      }
      return true;
    } catch (e) {
      if (ticket === generation.current && active.current) fail(e);
      return false;
    }
  }
  async function showNode(id: string) {
    const ticket = ++selection.current,
      scope = generation.current;
    setGroup(null);
    try {
      const p = params();
      p.set("node_id", id);
      const node = await api<KnowledgeNode>(path("node", p));
      if (
        ticket !== selection.current ||
        scope !== generation.current ||
        !active.current
      )
        return;
      if (session && node.job_id !== session)
        throw new Error(
          "선택한 세션에 속하지 않는 항목입니다. 전체 세션 조회를 사용하세요.",
        );
      if (!graph.nodes.some((n) => n.id === id) && !(await expand(id, true)))
        return;
      if (ticket !== selection.current || !active.current) return;
      setOrphans(true);
      setSelected(node);
      if (matchMedia("(max-width:760px)").matches) setList(false);
    } catch (e) {
      if (ticket === selection.current && active.current) fail(e);
    }
  }
  async function documentMore() {
    if (!selected) return;
    const ticket = selection.current,
      scope = generation.current,
      id = selected.id,
      p = new URLSearchParams({
        job_id: selected.job_id || "",
        path: selected.attrs?.artifact_path || "",
        content_hash: selected.attrs?.artifact_hash || "",
        offset: String(selected.document_next_offset),
      });
    setBusy(true);
    try {
      const page = await api(path("document", p));
      if (
        ticket !== selection.current ||
        scope !== generation.current ||
        !active.current
      )
        return;
      setSelected((current) =>
        current?.id === id
          ? {
              ...current,
              document: current.document + page.content,
              document_has_more: page.has_more,
              document_next_offset: page.next_offset,
            }
          : current,
      );
    } catch (e) {
      if (ticket === selection.current && active.current) fail(e);
    } finally {
      if (active.current) setBusy(false);
    }
  }
  async function previewProject() {
    const ticket = generation.current;
    try {
      setBusy(true);
      const op = await post("/api/admin/cleanup/preview", {
        scope: "projects",
        ids: [project],
      });
      if (ticket !== generation.current || !active.current) return;
      if (op.counts.jobs !== 0)
        throw new Error(
          "작업이 연결된 프로젝트입니다. 빈 프로젝트만 여기서 삭제할 수 있습니다.",
        );
      setProjectOperation({ ...op, project_id: project });
    } catch (e) {
      if (ticket === generation.current && active.current) fail(e);
    } finally {
      if (active.current) setBusy(false);
    }
  }
  return (
    <section
      className="knowledge-react"
      aria-labelledby="knowledge-title"
      onKeyDown={(e) => {
        if (e.key === "Escape" && !projectOperation) clear();
      }}
    >
      <header className="section-heading">
        <div>
          <span className="eyebrow">KNOWLEDGE</span>
          <h2 id="knowledge-title"><GraphIcon weight="duotone" size={26} aria-hidden />
            {admin ? "프로젝트 지식 그래프" : "결정과 명세 지식 그래프"}
          </h2>
          <p>저장된 결정, 근거와 명세의 관계를 살펴보세요.</p>
        </div>
      </header>
      {admin && (
        <div className="project-bar">
          <label>
            프로젝트
            <select
              id="admin-project"
              value={project}
              onChange={(e) => {
                invalidate();
                setProject(e.target.value);
                setSession("");
                setQuery("");
              }}
            >
              <option value="">프로젝트 선택</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} · {p.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          <p id="project-notice" role="status">
            {project
              ? "프로젝트의 저장된 지식을 조회합니다."
              : "조회할 프로젝트를 선택하세요."}
          </p>
          <button disabled={!project || busy} onClick={previewProject}>
            빈 프로젝트 삭제 미리보기
          </button>
        </div>
      )}
      <div className="knowledge-controls">
        <form
          id="knowledge-form"
          onSubmit={(e) => {
            e.preventDefault();
            void search();
          }}
        >
          <select
            id="knowledge-session"
            aria-label="대화 세션"
            value={session}
            onChange={(e) => {
              invalidate();
              setSession(e.target.value);
            }}
          >
            <option value="">전체 세션</option>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.request || "대화 세션"} · {s.id.slice(0, 8)}
              </option>
            ))}
          </select>
          <input
            id="knowledge-query"
            aria-label="검색"
            placeholder="지식 검색…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button disabled={busy}><MagnifyingGlassIcon size={18} aria-hidden />검색</button>
        </form>
        <div className="button-row">
          <button
            id="graph-summary"
            aria-pressed={mode === "summary"}
            onClick={() => {
              setMode("summary");
              setExpanded(new Set());
            }}
          >
            요약
          </button>
          <button
            id="graph-detail-mode"
            aria-pressed={mode === "detail"}
            onClick={() => setMode("detail")}
          >
            상세
          </button>
          <button
            id="graph-list-toggle"
            aria-expanded={list}
            onClick={() => setList(!list)}
          >
            <ListBulletsIcon size={18} aria-hidden />목록
          </button>
          <button id="graph-fit" onClick={() => handle.current?.fit()}>
            <ArrowsOutIcon size={18} aria-hidden />전체 맞춤
          </button>
        </div>
        <details className="graph-menu">
          <summary><FunnelIcon size={16} aria-hidden />필터</summary>
          <label>
            유형
            <select
              id="knowledge-kind"
              value={kind}
              onChange={(e) => {
                invalidate();
                setKind(e.target.value);
              }}
            >
              <option value="">전체 유형</option>
              {Object.entries(kinds).map(([v, t]) => (
                <option key={v} value={v}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label>
            상태
            <select
              id="knowledge-status"
              value={status}
              onChange={(e) => {
                invalidate();
                setStatus(e.target.value);
              }}
            >
              <option value="">현재 항목</option>
              <option value="confirmed">사용자 확정</option>
              <option value="proposed">LLM 제안</option>
              <option value="assumption">가정</option>
              <option value="superseded">대체된 항목</option>
            </select>
          </label>
        </details>
        <details className="graph-menu">
          <summary>설정</summary>
          <label>
            노드 간격
            <input
              id="graph-spacing"
              type="range"
              min="15"
              max="70"
              value={spacing}
              onChange={(e) => setSpacing(+e.target.value)}
            />
          </label>
          <label>
            연결 길이
            <input
              id="graph-distance"
              type="range"
              min="50"
              max="200"
              value={distance}
              onChange={(e) => setDistance(+e.target.value)}
            />
          </label>
          <label>
            라벨 양
            <input
              id="graph-label-amount"
              type="range"
              min="0"
              max="20"
              value={labels}
              onChange={(e) => setLabels(+e.target.value)}
            />
          </label>
          <label>
            <input
              id="graph-pause"
              type="checkbox"
              checked={paused}
              onChange={(e) => setPaused(e.target.checked)}
            />
            배치 일시정지
          </label>
          <button id="graph-layout" onClick={() => handle.current?.layout()}>
            전체 재배치
          </button>
        </details>
        {canRetry && (
          <button
            id="knowledge-retry"
            disabled={busy || mutationBusy}
            onClick={async () => {
              try {
                await post("/api/knowledge/retry", {});
                setNotice("미완료 청크 임베딩 재시도를 요청했습니다.");
              } catch (e) {
                fail(e);
              }
            }}
          >
            임베딩 재시도
          </button>
        )}
      </div>
      <p id="knowledge-notice" role="status" aria-live="polite">
        {notice ||
          (busy
            ? "조회 중…"
            : `화면 ${display.nodes.length}개 (명세 묶음 ${display.nodes.filter((n) => n.virtual).length}개) · 조회 항목 ${display.rawCount}개 · 실제 관계 ${display.rawEdges}개${graph.has_more ? " · 100개 제한으로 일부 표시" : ""}${display.rawCount && !display.rawEdges ? " · 현재 범위에 관계 없음" : ""}${results ? " · 검색 " + results.length + "개" : ""}`)}
      </p>
      <div className="react-graph-workspace">
        <KnowledgeGraph
          display={display}
          selected={selected?.id || ""}
          matches={matches}
          spacing={spacing}
          distance={distance}
          labels={labels}
          paused={paused}
          detail={mode === "detail"}
          onSelect={(n) => {
            if (n.virtual) {
              clear();
              setGroup(n);
            } else void showNode(n.id);
          }}
          onClear={clear}
          onRelation={setRelation}
          handle={handle}
        />
        {!display.nodes.length && !busy && (
          <p id="graph-empty" className="graph-empty">
            {graph.nodes.length
              ? "연결 없는 항목을 펼쳐보세요."
              : kind || status || query
                ? "현재 조회 조건에 맞는 항목이 없습니다."
                : "아직 저장된 지식이 없습니다."}
          </p>
        )}
        {list && (
          <aside
            id="knowledge-list"
            className="knowledge-drawer results-drawer"
            aria-label="지식 항목 · 검색 결과"
          >
            <header>
              <strong>지식 항목 · 검색 결과</strong>
              <button
                id="graph-list-close"
                aria-label="목록 닫기"
                onClick={() => setList(false)}
              >
                ×
              </button>
            </header>
            <ul id="knowledge-nodes" aria-label="지식 항목 목록">
              {(results || graph.nodes).map((n) => (
                <li key={n.id}>
                  <button onClick={() => void showNode(n.id)}>
                    {kinds[n.kind] || n.kind} · {n.body.slice(0, 90)}
                  </button>
                  {n.matches?.map((m, i) => (
                    <blockquote key={i}>{m.quote}</blockquote>
                  ))}
                </li>
              ))}
            </ul>
          </aside>
        )}
        {(selected || group) && (
          <aside
            id="graph-inspector"
            className="knowledge-drawer inspector-drawer"
            aria-label="선택한 지식 항목"
          >
            <header>
              <strong>선택 항목</strong>
              <button
                id="graph-detail-close"
                aria-label="상세 닫기"
                onClick={clear}
              >
                ×
              </button>
            </header>
            <div id="knowledge-detail">
              {group ? (
                <>
                  <h3>{group.label}</h3>
                  <p>같은 작업·문서 버전의 명세를 묶어 표시합니다.</p>
                  <button
                    onClick={() => {
                      setExpanded(
                        (previous) => new Set([...previous, group.id]),
                      );
                      setGroup(null);
                    }}
                  >
                    명세 묶음 펼치기
                  </button>
                  <ul>
                    {group.members.map((id: string) => (
                      <li key={id}>
                        <button onClick={() => void showNode(id)}>
                          {title(display.originals.get(id)!)}
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                selected && (
                  <>
                    <h3>
                      {kinds[selected.kind]} ·{" "}
                      {selected.active === false
                        ? "대체된 항목"
                        : (
                            {
                              confirmed: "사용자 확정",
                              proposed: "LLM 제안",
                              assumption: "가정",
                            } as Record<string, string>
                          )[selected.attrs?.status] || "현재 항목"}
                    </h3>
                    {selected.attrs?.origin === "demo" && (
                      <p>데모 실행에서 가져온 자료입니다.</p>
                    )}
                    <p>
                      세션:{" "}
                      {sessions.find((s) => s.id === selected.job_id)
                        ?.request || selected.job_id}
                    </p>
                    <Markdown content={selected.body} />
                    {selected.attrs?.rationale && (
                      <p>명시된 근거: {selected.attrs.rationale}</p>
                    )}
                    {selected.attrs?.conditions && (
                      <p>적용 조건: {selected.attrs.conditions}</p>
                    )}
                    {selected.attrs?.sources?.length > 0 && (
                      <p>
                        출처:{" "}
                        {[
                          ...new Set(
                            (selected.attrs?.sources || []).map(sourceLabel),
                          ),
                        ].join(", ")}
                      </p>
                    )}
                    {selected.attrs?.original_text && (
                      <pre>{selected.attrs.original_text}</pre>
                    )}
                    <div className="button-row">
                      <button onClick={() => void expand(selected.id)}>
                        주변 관계 펼치기
                      </button>
                      <button onClick={() => void expand(selected.id, true)}>
                        이 항목 중심으로 보기
                      </button>
                      <button onClick={() => void expand(selected.id, true, 2)}>
                        2단계 주변 보기
                      </button>
                    </div>
                    <ul>
                      {(selected.edges || [])
                        .filter(
                          (e: any) =>
                            e.source === selected.id ||
                            e.target === selected.id,
                        )
                        .map((e: any, i: number) => {
                          const other =
                            e.source === selected.id ? e.target : e.source;
                          return (
                            <li key={e.id || i}>
                              <button onClick={() => void showNode(other)}>
                                {e.source === selected.id ? "→" : "←"}{" "}
                                {edgeLabels[e.kind] || e.kind} ·{" "}
                                {(
                                  e.other_body ||
                                  display.originals.get(other)?.body ||
                                  "연결된 항목 열기"
                                ).slice(0, 70)}
                              </button>
                            </li>
                          );
                        })}
                    </ul>
                    {selected.document !== undefined && (
                      <details>
                        <summary>이 버전의 명세 원문</summary>
                        <pre>{selected.document}</pre>
                        {selected.document_has_more && (
                          <button
                            disabled={busy}
                            onClick={() => void documentMore()}
                          >
                            다음 내용 읽기
                          </button>
                        )}
                      </details>
                    )}
                  </>
                )
              )}
            </div>
          </aside>
        )}
      </div>
      <footer className="graph-footer">
        <div id="graph-legend">
          {Object.entries(kinds).map(([k, v]) => (
            <span key={k}>
              <i style={{ background: colors[k] }} />
              {v}
            </span>
          ))}
        </div>
        <p id="graph-relation" role="status">
          {relation}
        </p>
        <div className="button-row">
          <button
            id="graph-zoom-in"
            aria-label="그래프 확대"
            onClick={() => handle.current?.zoom(1.2)}
          >
            ＋
          </button>
          <button
            id="graph-zoom-out"
            aria-label="그래프 축소"
            onClick={() => handle.current?.zoom(1 / 1.2)}
          >
            −
          </button>
          {focused && (
            <button
              id="graph-back"
              onClick={() => {
                setMode("summary");
                setQuery("");
                setRefresh((r) => r + 1);
              }}
            >
              ← 전체 요약
            </button>
          )}
          {display.orphans.length > 0 && (
            <button id="graph-orphans" onClick={() => setOrphans(!orphans)}>
              {orphans ? "접기" : "펼치기"}: 이 범위에서 연결 없는 항목{" "}
              {display.orphans.length}개
            </button>
          )}
        </div>
      </footer>
      {projectOperation && (
        <ProjectDelete
          operation={projectOperation}
          busy={busy}
          onCancel={() => setProjectOperation(null)}
          onExecute={async () => {
            setBusy(true);
            try {
              await post("/api/admin/cleanup/execute", {
                id: projectOperation.id,
                confirmation: "",
              });
              setProjectOperation(null);
              invalidate();
              setProject("");
              setRefresh((r) => r + 1);
              onDeleted?.([]);
            } catch (e) {
              fail(e);
            } finally {
              setBusy(false);
            }
          }}
        />
      )}
    </section>
  );
}
function ProjectDelete({
  operation,
  busy,
  onCancel,
  onExecute,
}: {
  operation: any;
  busy: boolean;
  onCancel: () => void;
  onExecute: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    ref.current?.showModal();
    return () => {
      if (opener?.isConnected) opener.focus();
    };
  }, []);
  return (
    <dialog
      ref={ref}
      id="cleanup-dialog"
      onCancel={(e) => {
        if (busy) e.preventDefault();
        else onCancel();
      }}
    >
      <h2>빈 프로젝트 영구 삭제 확인</h2>
      <p>
        작업이 없는 프로젝트를 삭제합니다. 삭제한 기록은 복구할 수 없습니다.
      </p>
      <pre id="cleanup-summary">
        빈 프로젝트 1개 삭제{"\n"}
        {operation.project_id}
        {"\n"}
        {(operation.targets || []).join("\n")}
      </pre>
      <button id="cleanup-cancel" disabled={busy} autoFocus onClick={onCancel}>
        취소
      </button>
      <button id="cleanup-execute" disabled={busy} onClick={onExecute}>
        영구 삭제
      </button>
    </dialog>
  );
}
