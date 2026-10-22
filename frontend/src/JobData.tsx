// shadcn/ui dashboard-01의 데이터 표·카드 구성을 적용한다(MIT).
// https://github.com/shadcn-ui/ui/tree/ba1503c64472b82256d9de95e2e62c5901a38e8b
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ArrowsClockwiseIcon, ArrowRightIcon, DatabaseIcon, FileTextIcon, MagnifyingGlassIcon, ShieldWarningIcon, TrashIcon, UserCircleIcon, WarningCircleIcon } from "@phosphor-icons/react";
import { api, post } from "./api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "./components/ui/card";
import { Button } from "./components/ui/button";
import JobDetailSheet, { JobStatus, RecordId, jobStatusLabel } from "./JobDetailSheet";
import { filterJobs, jobTime, type CleanupOperation, type JobCatalog, type JobDetail, type JobRecord } from "./job-data";
import "./job-data.css";

const PAGE_SIZE = 25;
export default function JobData({ users, unowned, version, busy, save, refresh }: {
  users: { id: string }[]; unowned: { id: string }[]; version: number; busy: boolean;
  save: (path: string, payload: unknown) => Promise<any>; refresh: () => void;
}) {
  const [catalog, setCatalog] = useState<JobCatalog>({ jobs: [], pending: [] });
  const [loading, setLoading] = useState(true), [catalogError, setCatalogError] = useState("");
  const [query, setQuery] = useState(""), [owner, setOwner] = useState(""), [status, setStatus] = useState("");
  const [page, setPage] = useState(0), [selected, setSelected] = useState(new Set<string>());
  const [jobId, setJobId] = useState(""), [job, setJob] = useState<JobDetail | null>(null);
  const [jobLoading, setJobLoading] = useState(false), [jobError, setJobError] = useState(""), [tab, setTab] = useState("summary"), [retry, setRetry] = useState(0);
  const [working, setWorking] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [operation, setOperation] = useState<CleanupOperation | null>(null), [confirmation, setConfirmation] = useState(""), [cleanupError, setCleanupError] = useState("");
  const [params, setParams] = useSearchParams(), linkedId = params.get("job_id") || "";
  const alive = useRef(true), jobRequest = useRef(0), dialog = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLElement | null>(null), directInput = useRef<HTMLInputElement>(null);
  const disabled = busy || working;

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; jobRequest.current++; };
  }, []);
  useEffect(() => {
    let live = true;
    setLoading(true); setCatalogError(""); setSelected(new Set());
    api<JobCatalog>("/api/admin/cleanup/catalog")
      .then(value => { if (live) { setCatalog(value); setPage(0); } })
      .catch(e => { if (live) setCatalogError(e.message || "작업 목록을 불러오지 못했습니다."); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [version]);
  useEffect(() => {
    const ticket = ++jobRequest.current;
    setJob(null); setJobError(""); setTab("summary");
    if (!linkedId) { setJobLoading(false); return; }
    setJobId(linkedId); setJobLoading(true);
    api<JobDetail>("/api/admin/job?id=" + encodeURIComponent(linkedId))
      .then(value => { if (ticket === jobRequest.current && alive.current) setJob(value); })
      .catch(e => { if (ticket === jobRequest.current && alive.current) setJobError(e.message || "작업을 조회하지 못했습니다."); })
      .finally(() => { if (ticket === jobRequest.current && alive.current) setJobLoading(false); });
    return () => { jobRequest.current++; };
  }, [linkedId, retry]);
  useEffect(() => {
    if (!operation) return;
    const element = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    return () => { if (element?.isConnected) element.focus(); };
  }, [operation]);

  const jobs = useMemo(() => filterJobs(catalog.jobs, query, owner, status), [catalog.jobs, query, owner, status]);
  const visible = jobs.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const owners = [...new Set([...users.map(user => user.id), ...catalog.jobs.flatMap(item => item.owner_id ? [item.owner_id] : [])])].sort();
  const statuses = [...new Set(catalog.jobs.map(item => item.status || "unknown"))].sort();
  function resetSelection() { setSelected(new Set()); setPage(0); }
  function select(id: string, checked: boolean) {
    setSelected(current => { const next = new Set(current); checked ? next.add(id) : next.delete(id); return next; });
  }
  function open(id: string) {
    if (!id.trim()) return;
    opener.current = document.activeElement as HTMLElement | null;
    const next = new URLSearchParams(params); next.set("job_id", id.trim()); setParams(next);
  }
  function close() {
    jobRequest.current++;
    const next = new URLSearchParams(params); next.delete("job_id"); setParams(next, { replace: true });
  }
  async function preview(scope: string) {
    if (disabled || (scope === "jobs" && !selected.size)) return;
    setWorking(true); setError("");
    try {
      const value = await post<CleanupOperation>("/api/admin/cleanup/preview", { scope, ids: scope === "jobs" ? [...selected] : [] });
      if (alive.current) { setOperation(value); setConfirmation(""); setCleanupError(""); }
    } catch (e) { if (alive.current) setError((e as Error).message); }
    finally { if (alive.current) setWorking(false); }
  }
  async function execute(id: string, confirm = confirmation) {
    if (disabled) return;
    setWorking(true); setError(""); setCleanupError("");
    try {
      const result = await post<{ state: string }>("/api/admin/cleanup/execute", { id, confirmation: confirm });
      if (!alive.current) return;
      const deleted = operation?.targets || [];
      setOperation(null); setSelected(new Set());
      if (deleted.includes(linkedId)) close();
      setNotice(result.state === "completed" ? "정리를 완료했습니다." : "파일 정리가 남았습니다. 재시도하세요.");
      refresh();
      window.dispatchEvent(new CustomEvent("cleanup", { detail: { ids: deleted } }));
    } catch (e) {
      if (alive.current) { if (operation) setCleanupError((e as Error).message); else setError((e as Error).message); }
    } finally { if (alive.current) setWorking(false); }
  }
  const checkbox = (item: JobRecord) => <input type="checkbox" value={item.id} aria-label={`작업 ${item.id} 선택`}
    checked={selected.has(item.id)} onChange={event => select(item.id, event.target.checked)} />;

  return <div className="jobs-data">
    <fieldset className="jobs-controls" disabled={disabled} aria-busy={disabled}>
      <header className="jobs-heading">
        <div><span className="jobs-eyebrow"><DatabaseIcon size={16} aria-hidden /> JOBS & DATA</span><h2 id="job-title">작업·데이터</h2><p>작업과 사용자를 한눈에 확인하고 저장된 기록을 관리합니다.</p></div>
        <div className="jobs-heading-actions">
          <form id="job-form" onSubmit={event => { event.preventDefault(); open(jobId); }}>
            <label htmlFor="job-id">작업 ID</label><div><input ref={directInput} id="job-id" value={jobId} onChange={event => setJobId(event.target.value)} placeholder="ID로 바로 열기" required /><Button variant="outline" type="submit">조회</Button></div>
          </form>
          <Button id="cleanup-refresh" variant="outline" onClick={refresh} disabled={loading}><ArrowsClockwiseIcon size={16} aria-hidden />목록 새로고침</Button>
        </div>
      </header>
      <Card className="jobs-list-card">
        <CardHeader>
          <div className="jobs-list-heading"><CardTitle>작업 목록 <span>{loading ? "…" : catalog.jobs.length}</span></CardTitle><CardDescription>사용자는 현재 소유 사용자 ID 기준입니다. 시각은 한국 시간(KST)입니다.</CardDescription></div>
          <div className="jobs-filters">
            <label className="jobs-search" htmlFor="cleanup-query">작업 검색<div><MagnifyingGlassIcon size={17} aria-hidden /><input id="cleanup-query" type="search" value={query} placeholder="제목, 작업 ID, 사용자 ID 검색" onChange={event => { setQuery(event.target.value); resetSelection(); }} /></div></label>
            <label htmlFor="jobs-owner">사용자<select aria-label="사용자" id="jobs-owner" value={owner} onChange={event => { setOwner(event.target.value); resetSelection(); }}><option value="">전체 사용자</option><option value="unowned">소유자 없음</option>{owners.map(id => <option value={id} key={id}>{id}</option>)}</select></label>
            <label htmlFor="cleanup-status">상태<select aria-label="상태" id="cleanup-status" value={status} onChange={event => { setStatus(event.target.value); resetSelection(); }}><option value="">전체 상태</option>{statuses.map(value => <option value={value} key={value}>{jobStatusLabel(value === "unknown" ? undefined : value)}</option>)}</select></label>
            <Button variant="ghost" onClick={() => { setQuery(""); setOwner(""); setStatus(""); resetSelection(); }}>초기화</Button>
          </div>
        </CardHeader>
        <CardContent>
          {catalogError ? <div role="alert" className="jobs-error"><WarningCircleIcon size={20} aria-hidden /><p>{catalogError}</p><Button variant="outline" onClick={refresh}>목록 다시 조회</Button></div>
            : loading ? <p role="status" className="jobs-empty">작업 목록을 불러오는 중…</p>
              : <>
                <div className="jobs-list-summary"><label className="jobs-check"><input id="cleanup-select-all" type="checkbox" checked={visible.length > 0 && visible.every(item => selected.has(item.id))} disabled={!visible.length}
                  onChange={event => setSelected(event.target.checked ? new Set(visible.map(item => item.id)) : new Set())} />현재 페이지 전체 선택</label><span>검색 결과 {jobs.length}개 · 선택 {selected.size}개</span></div>
                {!visible.length ? <div className="jobs-empty"><FileTextIcon size={28} aria-hidden /><h3>조회된 작업이 없습니다</h3><p>검색어나 사용자·상태 필터를 변경해 보세요.</p></div> : <div id="cleanup-list">
                  <div className="jobs-table-scroll" tabIndex={0} aria-label="작업 목록 표">
                    <table><caption className="sr-only">작업 목록 · 최신 생성 시각순</caption><thead><tr><th>선택</th><th>작업 제목</th><th>상태</th><th>사용자</th><th>작업 ID</th><th>생성 시각 (KST)</th><th><span className="sr-only">상세 조회</span></th></tr></thead>
                      <tbody>{visible.map(item => <tr key={item.id}>
                        <td>{checkbox(item)}</td><td className="jobs-title-cell"><button type="button" className="jobs-title" onClick={() => open(item.id)}>{item.request || "제목 없는 작업"}</button></td>
                        <td><JobStatus status={item.status} /></td><td><RecordId value={item.owner_id} /></td><td><RecordId value={item.id} /></td><td className="jobs-time">{jobTime(item.created_at)}</td>
                        <td><Button variant="ghost" onClick={() => open(item.id)}>상세 조회<ArrowRightIcon size={14} aria-hidden /></Button></td>
                      </tr>)}</tbody>
                    </table>
                  </div>
                  <div className="jobs-mobile-list" role="list" aria-label="작업 카드 목록">{visible.map(item => <article role="listitem" className="jobs-mobile-item" key={item.id}>
                    <div className="jobs-mobile-heading">{checkbox(item)}<JobStatus status={item.status} /></div>
                    <button type="button" className="jobs-title" onClick={() => open(item.id)}>{item.request || "제목 없는 작업"}</button>
                    <dl><div><dt><UserCircleIcon size={14} aria-hidden />사용자</dt><dd><RecordId value={item.owner_id} /></dd></div><div><dt>작업 ID</dt><dd><RecordId value={item.id} /></dd></div><div><dt>생성 시각</dt><dd>{jobTime(item.created_at)}</dd></div></dl>
                    <Button variant="outline" onClick={() => open(item.id)}>상세 조회<ArrowRightIcon size={14} aria-hidden /></Button>
                  </article>)}</div>
                </div>}
                <div className="jobs-pagination"><span>{jobs.length ? `${page * PAGE_SIZE + 1}–${Math.min((page + 1) * PAGE_SIZE, jobs.length)} / ${jobs.length}개` : "0개"} · 최신 생성 시각순</span><div>
                  <Button variant="outline" disabled={page === 0} onClick={() => { setPage(value => value - 1); setSelected(new Set()); }}>이전</Button>
                  <Button variant="outline" disabled={(page + 1) * PAGE_SIZE >= jobs.length} onClick={() => { setPage(value => value + 1); setSelected(new Set()); }}>다음</Button>
                </div></div>
              </>}
        </CardContent>
      </Card>
      <div className="jobs-management">
        <Card><CardHeader><CardTitle>이관 전 기록 <span className="jobs-count">{unowned.length}</span></CardTitle><CardDescription>소유자가 없는 기존 기록에 사용자를 지정합니다.</CardDescription></CardHeader><CardContent>
          <details className="jobs-claim"><summary>소유자 없는 기록 관리</summary>
            {!unowned.length ? <p className="jobs-muted">소유자 없는 기록이 없습니다.</p> : unowned.map(item => <form key={item.id} onSubmit={async event => {
              event.preventDefault(); const result = await save("/api/admin/claim", { id: item.id, owner_id: new FormData(event.currentTarget).get("owner_id") });
              if (result && alive.current) setNotice("소유자를 지정했습니다.");
            }}><RecordId value={item.id} /><label>소유 사용자 ID<input name="owner_id" list="jobs-known-users" required /></label><Button variant="outline">소유자 지정</Button></form>)}
            <datalist id="jobs-known-users">{users.map(user => <option value={user.id} key={user.id} />)}</datalist>
          </details>
        </CardContent></Card>
        <Card><CardHeader><CardTitle id="cleanup-title">데이터 정리</CardTitle><CardDescription>삭제할 기록을 미리 확인한 뒤 정리합니다.</CardDescription></CardHeader><CardContent>
          <div className="jobs-selection"><span><strong>{selected.size}개</strong> 작업 선택됨</span><Button id="cleanup-selected" variant="outline" disabled={!selected.size || loading || !!catalogError} onClick={() => void preview("jobs")}><TrashIcon size={16} aria-hidden />선택 작업 삭제 미리보기</Button></div>
          <div id="cleanup-pending">{catalog.pending.map(id => <Button key={id} variant="outline" disabled={loading || !!catalogError} onClick={() => void execute(id, "")}><ArrowsClockwiseIcon size={16} aria-hidden />남은 파일 정리 재시도 · {id}</Button>)}</div>
          <details className="jobs-danger"><summary><ShieldWarningIcon size={17} aria-hidden />위험 작업 · 전체 기록 삭제</summary><p>모든 작업과 저장된 기록을 영구 삭제합니다. 미리보기에서 대상을 확인하세요.</p><Button id="cleanup-all" variant="outline" disabled={loading || !!catalogError} onClick={() => void preview("all")}>전체 기록 삭제 미리보기</Button></details>
        </CardContent></Card>
      </div>
    </fieldset>
    {error && <p className="jobs-error" role="alert">{error}</p>}
    <p id="cleanup-notice" role="status">{notice}</p>
    <JobDetailSheet id={linkedId} job={job} fallback={catalog.jobs.find(item => item.id === linkedId)} loading={jobLoading} error={jobError}
      tab={tab} setTab={setTab} close={close} retry={() => setRetry(value => value + 1)}
      restoreFocus={() => { if (opener.current?.isConnected) opener.current.focus(); else directInput.current?.focus(); }} />
    {operation && <dialog ref={dialog} id="cleanup-dialog" className="jobs-cleanup-dialog" aria-labelledby="cleanup-dialog-title" onCancel={event => { if (disabled) event.preventDefault(); else setOperation(null); }}>
      <span className="jobs-eyebrow"><ShieldWarningIcon size={17} aria-hidden /> DELETE CONFIRMATION</span><h2 id="cleanup-dialog-title">영구 삭제 확인</h2>
      <pre id="cleanup-summary">{`대상 작업 ${operation.counts.jobs}개 · 파일 ${operation.counts.files || 0}개\n${(operation.targets || [...selected]).join("\n")}\n다른 작업의 출처 연결 ${operation.external_references || 0}개 제거 · 공통 결정 ${operation.counts.project_decisions || 0}개 신규 재사용 중단 · 제외 폴더 ${(operation.skipped || []).length}개\n삭제한 기록은 복구할 수 없습니다. 미리보기는 10분 동안 유효합니다.`}</pre>
      {operation.scope === "all" && <label id="cleanup-confirm-label">계속하려면 “전체 기록 삭제”를 입력하세요.<input id="cleanup-confirm" value={confirmation} autoComplete="off" onChange={event => setConfirmation(event.target.value)} disabled={disabled} /></label>}
      <p id="cleanup-error" role="alert">{cleanupError}</p><div className="jobs-dialog-actions"><Button id="cleanup-cancel" variant="outline" autoFocus disabled={disabled} onClick={() => setOperation(null)}>취소</Button>
        <Button id="cleanup-execute" disabled={disabled || (operation.scope === "all" && confirmation !== "전체 기록 삭제")} onClick={() => void execute(operation.id)}>영구 삭제</Button>
      </div>
    </dialog>}
  </div>;
}
