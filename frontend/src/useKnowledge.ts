import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, post } from "./api";
import { useAuth } from "./Auth";
import { build, type KnowledgeGraph as GraphData, type KnowledgeNode } from "./graph-data";
import type { GraphHandle } from "./KnowledgeGraph";
const empty: GraphData = { nodes: [], edges: [] };
export function useKnowledge({ admin, selectedJobId, onDeleted }: { admin: boolean; selectedJobId?: string; onDeleted?: (ids: string[]) => void }) {
  const auth = useAuth(),
    canRetry = !auth.publicMode || auth.user?.role === "admin",
    mutationBusy =
      auth.status.ready === false || auth.status.checkState === "error";
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
    [newRequirement, setNewRequirement] = useState(false),
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
    setNewRequirement(false);
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
    setNewRequirement(false);
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
      setNewRequirement(false);
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
  const beginRequirement = () => { selection.current++; setSelected(null); setGroup(null); setNewRequirement(true); };
  async function retryEmbeddings() {
    try { await post("/api/knowledge/retry", {}); setNotice("미완료 청크 임베딩 재시도를 요청했습니다."); }
    catch (e) { fail(e); }
  }
  async function deleteProject() {
    setBusy(true);
    try {
      await post("/api/admin/cleanup/execute", { id: projectOperation.id, confirmation: "" });
      setProjectOperation(null); invalidate(); setProject(""); setRefresh(value => value+1); onDeleted?.([]);
    } catch(e) { fail(e); }
    finally { setBusy(false); }
  }
  return {
    canRetry, mutationBusy, projects, project, setProject,
    sessions, session, setSession, query, setQuery,
    kind, setKind, status, setStatus, graph,
    results, matches, selected, group, setGroup,
    newRequirement, mode, setMode, setExpanded, orphans,
    setOrphans, list, setList, notice, busy,
    spacing, setSpacing, distance, setDistance, labels,
    setLabels, paused, setPaused, relation, setRelation,
    setRefresh, focused, projectOperation, setProjectOperation, handle,
    display, clear, search, expand, showNode,
    documentMore, previewProject, invalidate, beginRequirement, retryEmbeddings,
    deleteProject,
  };
}
