import { decodeStepDetail, type StepDetail } from "../execution/execution-detail";
import { decodeJob, decodeJobs } from "./job-response";
import { decodeEvent } from "./event-response";
import { applyProgress, type ProgressState } from "./progress-state";
import { automaticStep } from "../execution/step-selection";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../auth/Auth";
import { api, post } from "../../shared/api/api";
import type { Job, CommandSelections, Step } from "../../shared/types";

function useResource<T>(path: string | undefined, revision: number, owner: string | undefined, onError: (message: string) => void, decode: (value: unknown) => T) {
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
    api(path, { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) setValue({ path, owner, data: decode(data) });
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
  const [detailRevision, setDetailRevision] = useState(0);
  const submitting = useRef(false), manual = useRef(false);
  const selected = useRef(id);
  const stream = useRef<WebSocket | undefined>(undefined);
  const progressRef = useRef<ProgressState | undefined>(undefined);
  const resyncPending = useRef(false);
  const [pushed, setPushed] = useState<{ owner?: string; progress: ProgressState }>();
  const [listChanges, setListChanges] = useState<{ owner?: string; jobs: Record<string, { job: Job; revision: number }> }>({ jobs: {} });
  const [listBase, setListBase] = useState<{ owner?: string; jobs: Job[] }>();
  const [deletedIds, setDeletedIds] = useState<{ owner?: string; ids: string[] }>({ ids: [] });
  selected.current = id;
  const views = useRef(new Map<string, { step: string; tab: string; manual: boolean }>());
  const refresh = useCallback(() => setRevision(value => value + 1), []);
  const jobs = useResource<Job[]>("/api/jobs", revision, auth.user?.id, auth.setNotice, decodeJobs);
  const current = useResource<Job>(id ? `/api/jobs/${encodeURIComponent(id)}` : undefined, revision, auth.user?.id, auth.setNotice, decodeJob);
  const job = pushed && pushed.owner === auth.user?.id && pushed.progress.job.id === id ? pushed.progress.job : current.data;
  const nodes: Step[] = [...(job?.execution_graph?.nodes || []), ...(job?.completed_documents || [])];
  const node = nodes.find(item => item.id === step);
  const detail = useResource<StepDetail>(id && step && node?.detail_available
    ? `/api/jobs/${encodeURIComponent(id)}/steps/${encodeURIComponent(step)}` : undefined,
    detailRevision, auth.user?.id, auth.setNotice, decodeStepDetail);

  useEffect(() => {
    progressRef.current = undefined;
    resyncPending.current = true;
    setPushed(undefined);
    const socket = stream.current;
    if (id && socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ event: "job.subscribe", job_id: id }));
    return () => {
      if (id && socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ event: "job.unsubscribe", job_id: id }));
    };
  }, [id, auth.user?.id]);

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
      setStep(automaticStep(nodes, job.state?.status || job.status));
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
      stream.current = socket;
      socket.onopen = () => {
        attempt = 0; progressRef.current = undefined; resyncPending.current = true;
        setConnection("실시간 상태를 동기화하고 있습니다.");
        if (selected.current) socket?.send(JSON.stringify({ event: "job.subscribe", job_id: selected.current }));
      };
      socket.onmessage = event => {
        if (!alive) return;
        let value;
        try { value = decodeEvent(JSON.parse(event.data)); } catch { return; }
        if (value.event === "session.expired") {
          alive = false;
          setPushed(undefined); setListBase(undefined); setListChanges({ jobs: {} });
          socket?.close();
          window.dispatchEvent(new Event("signed-out"));
          return;
        }
        if (value.event === "jobs.snapshot") {
          setListBase({ owner: auth.user?.id, jobs: value.jobs });
          setListChanges({ owner: auth.user?.id, jobs: Object.fromEntries(value.jobs.map(job => [job.id, { job, revision: value.revisions[job.id] || 0 }])) });
          setDeletedIds({ owner: auth.user?.id, ids: [] });
          if (!selected.current) setConnection("");
        }
        if (value.event === "job.snapshot" || value.event === "job.progress") {
          if (value.job_id !== selected.current) return;
          const result = applyProgress(progressRef.current, value);
          if (result.resync) {
            if (!resyncPending.current) socket?.send(JSON.stringify({ event: "job.resync", job_id: value.job_id }));
            resyncPending.current = true;
            return;
          }
          if (value.event === "job.snapshot") resyncPending.current = false;
          if (result.state) {
            progressRef.current = result.state;
            setPushed({ owner: auth.user?.id, progress: result.state });
            setConnection("");
          }
        }
        if (value.event === "jobs.changed") setListChanges(previous => {
          const entries = previous.owner === auth.user?.id ? previous.jobs : {};
          if ((entries[value.job_id]?.revision || 0) >= value.revision) return previous;
          return { owner: auth.user?.id, jobs: { ...entries, [value.job_id]: { job: value.job, revision: value.revision } } };
        });
        if (value.event === "job.subscription_error") setConnection("실시간 상태를 구독할 수 없습니다. 작업 접근 권한과 서버 연결을 확인하세요.");
        if (value.event === "records.deleted") {
          setDeletedIds(previous => ({ owner: auth.user?.id, ids: [...(previous.owner === auth.user?.id ? previous.ids : []), ...value.ids] }));
          for (const deleted of value.ids || []) {
            views.current.delete(deleted);
            const prefix = `draft:${auth.user?.id || "local"}:${deleted}:`;
            for (const key of Object.keys(sessionStorage)) if (key.startsWith(prefix)) sessionStorage.removeItem(key);
          }
          if (selected.current && value.ids.includes(selected.current)) navigate("/");
          window.dispatchEvent(new Event("cleanup")); refresh();
        }
        if (value.event === "service.status") window.dispatchEvent(new CustomEvent("service-status", { detail: value.status }));
        if (value.event === "server_error") socket?.close();
      };
      socket.onclose = () => {
        if (!alive) return;
        setConnection("작업 서버 연결이 끊어졌습니다. 재연결 중입니다.");
        retry = setTimeout(connect, Math.min(1000 * 2 ** attempt++, 10000) * (0.8 + Math.random() * 0.4));
      };
      socket.onerror = () => socket?.close();
    };
    connect();
    const close = () => { alive = false; clearTimeout(retry); socket?.close(); stream.current = undefined; };
    const show = (event: PageTransitionEvent) => { if (event.persisted) setEpoch(value => value + 1); };
    window.addEventListener("pagehide", close); window.addEventListener("pageshow", show);
    return () => { close(); window.removeEventListener("pagehide", close); window.removeEventListener("pageshow", show); };
  }, [auth.user?.id, epoch, navigate, refresh]);

  async function command(kind: string, input?: unknown, selections: CommandSelections = {}) {
    if (submitting.current) return null;
    submitting.current = true; setBusy(true);
    try {
      const result = decodeJob(await post("/api/commands", kind === "generate" ? { kind, input, ...selections }
        : { kind, job_id: id, execution_id: job?.execution_id, input,
          ...(kind === "retry" && selections.replay_pending ? { replay_pending: true } : {}),
          ...(kind === "approve" ? { accept_remaining_issues: selections.accept_remaining_issues === true, evaluation_hash: job?.state?.rubric_review?.evaluation_hash } : {}),
          candidate_hash: kind === "approve" ? job?.state?.candidate_hash : undefined }));
      if (result.id === selected.current) {
        const progress = { job: result, revision: 0, serverOffset: 0 };
        progressRef.current = undefined;
        resyncPending.current = true;
        setPushed({ owner: auth.user?.id, progress });
        if (stream.current?.readyState === WebSocket.OPEN) stream.current.send(JSON.stringify({ event: "job.resync", job_id: result.id }));
      }
      return result;
    } finally {
      submitting.current = false; setBusy(false);
      void auth.refreshStatus().catch(() => {});
    }
  }
  const changes = listChanges.owner === auth.user?.id ? listChanges.jobs : {};
  const listed = (listBase?.owner === auth.user?.id ? listBase?.jobs || jobs.data || [] : jobs.data || []).map(item => ({ ...item, ...changes[item.id]?.job }));
  for (const entry of Object.values(changes)) if (!listed.some(item => item.id === entry.job.id)) listed.unshift(entry.job);
  const removed = deletedIds.owner === auth.user?.id ? deletedIds.ids : [];
  return { jobs: listed.filter(item => !removed.includes(item.id)), job, step, tab, setTab, busy, loading: current.loading, connection, refresh, command,
    detail: detail.error ? { unavailable: true, message: detail.error } : node?.detail_available ? detail.data : { unavailable: true, message: "이 단계의 상세 기록이 저장되지 않았습니다." },
    select: (value: string) => { manual.current = true; setStep(value); setDetailRevision(previous => previous + 1); },
  };
}
