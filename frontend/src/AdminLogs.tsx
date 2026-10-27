import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import "./admin-logs.css";

type Row = { timestamp: string; service: string; level: string; event: string; message: string; fields: Record<string, string> };
type Result = { items: Row[]; start: string; end: string; next_offset: number | null; storage: { state: string } };
type Status = { state: string; retention_days: number; collector_seen: boolean; free_bytes: number | null; warnings: string[] };
const services = ["backend", "gateway", "caddy", "postgresql"];
const levels = ["debug", "info", "warning", "error", "critical", "unknown"];

export default function AdminLogs() {
  const [query, setQuery] = useState(""), [tick, setTick] = useState(0);
  const [result, setResult] = useState<Result | null>(null), [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState(""), [statusError, setStatusError] = useState("");
  const [busy, setBusy] = useState(false), [automatic, setAutomatic] = useState(true), [notice, setNotice] = useState("");
  const controller = useRef<AbortController | null>(null), generation = useRef(0);
  const previousQuery = useRef<string | null>(null);

  useEffect(() => {
    const version = ++generation.current;
    const abort = new AbortController(); controller.current?.abort(); controller.current = abort;
    setBusy(true); setError("");
    if (previousQuery.current !== query) { setResult(null); previousQuery.current = query; }
    const params = new URLSearchParams(query);
    const minutes = Number(params.get("period") || 15); params.delete("period");
    params.set("start", new Date(Date.now() - minutes * 60000 + (minutes === 10080 ? 1000 : 0)).toISOString());
    api<Result>("/api/admin/logs?" + params, { signal: abort.signal })
      .then(value => { if (version === generation.current && !abort.signal.aborted) setResult(value); })
      .catch(e => { if (!abort.signal.aborted) { setAutomatic(false); setError(e.message); } })
      .finally(() => { if (!abort.signal.aborted) setBusy(false); });
    return () => { abort.abort(); controller.current?.abort(); generation.current++; };
  }, [query, tick]);

  useEffect(() => {
    if (!automatic) return;
    const timer = window.setInterval(() => { if (!document.hidden && !busy) setTick(v => v + 1); }, 5000);
    return () => window.clearInterval(timer);
  }, [automatic, busy]);

  useEffect(() => {
    let active = true, pending = false;
    const abort = new AbortController();
    const load = async () => {
      if (document.hidden || pending) return;
      pending = true;
      try { const value = await api<Status>("/api/admin/logs/status", { signal: abort.signal }); if (active) { setStatus(value); setStatusError(""); } }
      catch (e) { if (active && !abort.signal.aborted) setStatusError(e instanceof Error ? e.message : "수집 상태를 확인할 수 없습니다."); }
      finally { pending = false; }
    };
    void load(); const timer = window.setInterval(() => void load(), 30000);
    return () => { active = false; abort.abort(); window.clearInterval(timer); };
  }, []);

  async function more() {
    if (!result || result.next_offset === null || busy) return;
    setAutomatic(false); setBusy(true); setError("");
    const version = generation.current;
    const params = new URLSearchParams(query);
    params.delete("period");
    params.set("start", result.start); params.set("end", result.end); params.set("offset", String(result.next_offset));
    const abort = new AbortController(); controller.current = abort;
    try {
      const value = await api<Result>("/api/admin/logs?" + params, { signal: abort.signal });
      if (!abort.signal.aborted && version === generation.current) setResult({ ...value, items: [...result.items, ...value.items] });
    } catch (e) { if (!abort.signal.aborted) setError(e instanceof Error ? e.message : "로그를 불러오지 못했습니다."); }
    finally { if (!abort.signal.aborted && version === generation.current) setBusy(false); }
  }

  return <section className="admin-logs" aria-labelledby="logs-title">
    <header className="logs-heading"><div><h2 id="logs-title">컨테이너 로그</h2><p>MAGI 서비스의 최근 7일 기록을 한곳에서 확인합니다.</p></div>
      <div className="logs-controls"><label><input type="checkbox" checked={automatic} onChange={e => { setAutomatic(e.target.checked); if (e.target.checked) setTick(v => v + 1); }} />5초 자동 갱신</label>
        <button type="button" disabled={busy} onClick={() => setTick(v => v + 1)}>새로고침</button></div>
    </header>
    <div className="logs-status" role="status">
      <span>저장소: {statusError ? "확인 불가" : status ? "연결됨" : "확인 중"}</span>
      <span>수집기: {status ? status.collector_seen ? "최근 신호 있음" : "신호 없음" : "확인 중"}</span>
      {status?.free_bytes != null && <span>디스크 여유 {(status.free_bytes / 1024 ** 3).toFixed(1)} GiB</span>}
      {statusError && <p>{statusError}</p>}{status?.warnings.map(w => <p key={w}>{w}</p>)}
    </div>
    <form className="logs-filters" onSubmit={e => {
      e.preventDefault(); const data = new FormData(e.currentTarget); const params = new URLSearchParams();
      const minutes = Number(data.get("period") || 15);
      params.set("period", String(minutes));
      for (const key of ["service", "level", "q", "trace_id", "job_id", "execution_id"]) { const value = String(data.get(key) || "").trim(); if (value) params.set(key, value); }
      setQuery(params.toString()); setTick(v => v + 1); setNotice("");
    }}>
      <label>서비스<select name="service"><option value="">전체 서비스</option>{services.map(v => <option key={v}>{v}</option>)}</select></label>
      <label>레벨<select name="level"><option value="">전체 레벨</option>{levels.map(v => <option key={v}>{v}</option>)}</select></label>
      <label>기간<select name="period" defaultValue="15">{[[15, "최근 15분"], [60, "최근 1시간"], [1440, "최근 24시간"], [10080, "최근 7일"]].map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></label>
      <label className="logs-search">메시지 검색<input name="q" maxLength={256} placeholder="메시지에 포함된 문자열" /></label>
      {[['trace_id', '추적 ID'], ['job_id', '작업 ID'], ['execution_id', '실행 ID']].map(([key, label]) => <label key={key}>{label}<input name={key} maxLength={64} /></label>)}
      <button type="submit">검색</button>
    </form>
    <p role="alert">{error}</p><p role="status">{notice}</p>
    <div className="logs-summary" aria-live="polite"><span>{result ? `${result.items.length}건 · 기준 ${new Date(result.end).toLocaleString("ko-KR")}` : busy ? "로그를 불러오는 중…" : "조회 결과 없음"}</span><span>{automatic ? "자동 갱신 중" : "갱신 일시정지"}</span></div>
    <div className="logs-list" aria-busy={busy} onWheel={() => setAutomatic(false)} onTouchMove={() => setAutomatic(false)}>
      {result?.items.length === 0 && <p className="logs-empty">조건에 맞는 로그가 없습니다.</p>}
      {result?.items.map((row, index) => <details className={`logs-row logs-${row.level}`} key={`${row.timestamp}:${index}`} onToggle={e => { if (e.currentTarget.open) setAutomatic(false); }}>
        <summary><time dateTime={row.timestamp}>{new Date(row.timestamp).toLocaleString("ko-KR")}</time><span className="logs-service">{row.service}</span><span className="logs-level">{row.level}</span><span className="logs-message">{row.message}</span></summary>
        <div className="logs-detail"><pre>{JSON.stringify(row, null, 2)}</pre><button type="button" onClick={() => { void navigator.clipboard.writeText(JSON.stringify(row, null, 2)).then(() => setNotice("로그를 복사했습니다."), () => setNotice("로그를 복사하지 못했습니다.")); }}>로그 복사</button></div>
      </details>)}
    </div>
    {result?.next_offset != null && <button type="button" disabled={busy || result.items.length >= 10000} onClick={() => void more()}>이전 로그 더 보기</button>}
    <p className="logs-footnote">수집 이전에 삭제된 기록은 표시되지 않습니다. 저장소와 수집기 상태는 최대 30초 간격으로 확인합니다.</p>
  </section>;
}
