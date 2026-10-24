import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "./Auth";
import { api, post } from "./api";
import type { Job, RecordData, Step } from "./types";

function useResource<T>(path: string | undefined, revision: number, owner: string | undefined, onError: (message: string) => void) {
  const [value, setValue] = useState<{ path: string; owner: string | undefined; data: T } | null>(null);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const error = useRef(onError);
  error.current = onError;
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    setLoading(true);
    setFailure(null);
    api<T>(path, { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) setValue({ path, owner, data });
    }).catch(e => {
      if (!controller.signal.aborted) { setFailure(e.message); error.current(e.message); }
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [path, revision, owner]);
  return { data: value && value.path === path && value.owner === owner ? value.data : null, loading: !!path && loading, error: failure };
}

export function useJobSession() {
  const { id } = useParams(), location = useLocation(), navigate = useNavigate(), auth = useAuth();
  const [revision, setRevision] = useState(0), [connection, setConnection] = useState("");
  const [tab, setTab] = useState("conversation"), [step, setStep] = useState("");
  const [busy, setBusy] = useState(false), [epoch, setEpoch] = useState(0);
  const submitting = useRef(false), manual = useRef(false);
  const selected = useRef(id);
  selected.current = id;
  const views = useRef(new Map<string, { step: string; tab: string; manual: boolean }>());
  const refresh = useCallback(() => setRevision(value => value + 1), []);
  const jobs = useResource<Job[]>("/api/jobs", revision, auth.user?.id, auth.setNotice);
  const current = useResource<Job>(id ? `/api/jobs/${encodeURIComponent(id)}` : undefined, revision, auth.user?.id, auth.setNotice);
  const job = current.data;
  const nodes: Step[] = [...(job?.execution_graph?.nodes || []), ...(job?.completed_documents || [])];
  const node = nodes.find(item => item.id === step);
  const detail = useResource<RecordData>(id && step && node?.detail_available
    ? `/api/jobs/${encodeURIComponent(id)}/steps/${encodeURIComponent(step)}` : undefined,
    revision, auth.user?.id, auth.setNotice);

  useEffect(() => {
    views.current.clear();
  }, [auth.user?.id]);
  useEffect(() => {
    const saved = id ? views.current.get(id) : undefined;
    manual.current = saved?.manual || false;
    setStep(saved?.step || "");
    setTab(saved?.tab || "conversation");
  }, [id]);
  useEffect(() => {
    if (!id || job?.id !== id) return;
    const requested = new URLSearchParams(location.search).get("completed_id");
    if (requested && !manual.current && nodes.some(item => item.id === requested)) {
      manual.current = true; setStep(requested); setTab("document");
    } else if (!manual.current || !nodes.some(item => item.id === step)) {
      const document = [...nodes].reverse().find(item => item.has_document);
      setStep((document || nodes.at(-1))?.id || "");
    }
    if (!["queued", "running"].includes(job.status) && ["작업을 대기열에 넣었습니다.", "새 작업을 대기열에 넣었습니다."].includes(auth.notice)) auth.setNotice("");
  }, [id, job, location.search]);
  useEffect(() => {
    if (id && job?.id === id) views.current.set(id, { step, tab, manual: manual.current });
  }, [id, job?.id, step, tab]);

  useEffect(() => {
    let alive = true, socket: WebSocket | undefined, retry: ReturnType<typeof setTimeout> | undefined, attempt = 0;
    const connect = () => {
      if (!alive) return;
      socket = new WebSocket(`${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws/events`);
      socket.onopen = () => { attempt = 0; setConnection(""); refresh(); window.dispatchEvent(new Event("service-status")); };
      socket.onmessage = event => {
        if (!alive) return;
        let value;
        try { value = JSON.parse(event.data); } catch { return; }
        if (["ready", "job.changed"].includes(value.event)) refresh();
        if (value.event === "records.deleted") {
          for (const deleted of value.ids || []) {
            views.current.delete(deleted);
            const prefix = `draft:${auth.user?.id || "local"}:${deleted}:`;
            for (const key of Object.keys(sessionStorage)) if (key.startsWith(prefix)) sessionStorage.removeItem(key);
          }
          if (value.ids?.includes(selected.current)) navigate("/");
          window.dispatchEvent(new Event("cleanup")); refresh();
        }
        if (value.event === "service.status") window.dispatchEvent(new CustomEvent("service-status", { detail: value.status }));
        if (value.event === "server_error") socket?.close();
      };
      socket.onclose = () => {
        if (!alive) return;
        setConnection("작업 서버 연결이 끊어졌습니다. 재연결 중입니다.");
        retry = setTimeout(connect, Math.min(1000 * 2 ** attempt++, 10000));
      };
      socket.onerror = () => socket?.close();
    };
    connect();
    const poll = setInterval(refresh, 15000);
    const close = () => { alive = false; clearTimeout(retry); clearInterval(poll); socket?.close(); };
    const show = (event: PageTransitionEvent) => { if (event.persisted) setEpoch(value => value + 1); };
    window.addEventListener("pagehide", close); window.addEventListener("pageshow", show);
    return () => { close(); window.removeEventListener("pagehide", close); window.removeEventListener("pageshow", show); };
  }, [auth.user?.id, epoch, navigate, refresh]);

  async function command(kind: string, input?: unknown, selections: RecordData = {}) {
    if (submitting.current) return null;
    submitting.current = true; setBusy(true);
    try {
      const result = await post<Job>("/api/commands", kind === "generate" ? { kind, input, ...selections }
        : { kind, job_id: id, execution_id: job?.execution_id, input,
          candidate_hash: kind === "approve" ? job?.state?.candidate_hash : undefined });
      refresh();
      return result;
    } finally {
      submitting.current = false; setBusy(false);
      void auth.refreshStatus().catch(() => {});
    }
  }
  return { jobs: jobs.data || [], job, step, tab, setTab, busy, loading: current.loading, connection, refresh, command,
    detail: detail.error ? { unavailable: true, message: detail.error } : node?.detail_available ? detail.data : { unavailable: true, message: "이 단계의 상세 기록이 저장되지 않았습니다." },
    select: (value: string) => { manual.current = true; setStep(value); },
  };
}
