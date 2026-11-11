import { VStack } from "@astryxdesign/core/VStack";
import { HStack } from "@astryxdesign/core/HStack";
import { Table, TableHeader, TableBody, TableRow, TableHeaderCell, TableCell } from "@astryxdesign/core/Table";
import { NativeSelect } from "../../shared/ui/native-select";
import { Input } from "../../shared/ui/input";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { decodeCatalog, decodeAdminJob, decodeCleanup, decodeCleanupResult } from "./admin-response";
// shadcn/ui dashboard-01의 데이터 표·카드 구성을 적용한다(MIT).
// https://github.com/shadcn-ui/ui/tree/ba1503c64472b82256d9de95e2e62c5901a38e8b
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ArrowsClockwiseIcon, ArrowRightIcon, DatabaseIcon, FileTextIcon, MagnifyingGlassIcon, ShieldWarningIcon, TrashIcon, UserCircleIcon, WarningCircleIcon } from "@phosphor-icons/react";
import { api, post } from "../../shared/api/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../shared/ui/card";
import { Button } from "../../shared/ui/button";
import { InputGroup, InputGroupAddon, InputGroupInput } from "../../shared/ui/input-group";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "../../shared/ui/dialog";
import JobDetailSheet, { JobStatus, RecordId, jobStatusLabel } from "./JobDetailSheet";
import { filterJobs, jobTime, type CleanupOperation, type JobCatalog, type JobDetail, type JobRecord } from "./job-data";
import "./job-data.css";

const PAGE_SIZE = 25;
export default function JobData({ users, version, busy, refresh }: {
  users: { id: string }[]; version: number; busy: boolean;
  refresh: () => void;
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
  const alive = useRef(true), jobRequest = useRef(0), executing = useRef(false);
  const cleanupOpener = useRef<HTMLElement | null>(null), cleanupCancel = useRef<HTMLButtonElement | null>(null);
  const opener = useRef<HTMLElement | null>(null), directInput = useRef<HTMLInputElement>(null);
  const disabled = busy || working;

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; jobRequest.current++; };
  }, []);
  useEffect(() => {
    let live = true;
    setLoading(true); setCatalogError(""); setSelected(new Set());
    api("/api/admin/cleanup/catalog").then(decodeCatalog)
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
    api("/api/admin/job?id=" + encodeURIComponent(linkedId)).then(decodeAdminJob)
      .then(value => { if (ticket === jobRequest.current && alive.current) setJob(value); })
      .catch(e => { if (ticket === jobRequest.current && alive.current) setJobError(e.message || "작업을 조회하지 못했습니다."); })
      .finally(() => { if (ticket === jobRequest.current && alive.current) setJobLoading(false); });
    return () => { jobRequest.current++; };
  }, [linkedId, retry]);
  useEffect(() => {
    if (!operation) return;
    // 2026-11-11: 파괴적 동작은 취소에 먼저 포커스하고 원래 호출 위치로 돌아간다.
    cleanupCancel.current?.focus();
    return () => {
      const target = cleanupOpener.current;
      if (target?.isConnected && !(target instanceof HTMLButtonElement && target.disabled)) target.focus();
      else directInput.current?.focus();
    };
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
    cleanupOpener.current = document.activeElement as HTMLElement | null;
    setWorking(true); setError("");
    try {
      const value = await post("/api/admin/cleanup/preview", { scope, ids: scope === "jobs" ? [...selected] : [] }).then(decodeCleanup);
      if (alive.current) { setOperation(value); setConfirmation(""); setCleanupError(""); }
    } catch (e) { if (alive.current) setError((e as Error).message); }
    finally { if (alive.current) setWorking(false); }
  }
  async function execute(id: string, confirm = confirmation) {
    if (disabled || executing.current) return;
    executing.current = true;
    setWorking(true); setError(""); setCleanupError("");
    try {
      const result = await post("/api/admin/cleanup/execute", { id, confirmation: confirm }).then(decodeCleanupResult);
      if (!alive.current) return;
      const deleted = operation?.targets || [];
      setOperation(null); setSelected(new Set());
      if (deleted.includes(linkedId)) close();
      setNotice(result.state === "completed" ? "정리를 완료했습니다." : "파일 정리가 남았습니다. 재시도하세요.");
      refresh();
      window.dispatchEvent(new CustomEvent("cleanup", { detail: { ids: deleted } }));
    } catch (e) {
      if (alive.current) { if (operation) setCleanupError((e as Error).message); else setError((e as Error).message); }
    } finally { executing.current = false; if (alive.current) setWorking(false); }
  }
  const checkbox = (item: JobRecord) => <CheckboxInput label={`작업 ${item.id} 선택`} isLabelHidden
    value={selected.has(item.id)} onChange={checked => select(item.id, checked)} />;

  return <VStack gap={2} className="jobs-data">
    <fieldset className="jobs-controls" disabled={disabled} aria-busy={disabled}>
      <header className="jobs-heading">
        <div><h2 id="job-title"><DatabaseIcon size={20} aria-hidden /> 작업 데이터</h2><p>작업과 사용자를 확인하고 저장된 기록을 관리합니다.</p></div>
        <HStack gap={2} wrap="wrap" className="jobs-heading-actions">
          <form id="job-form" onSubmit={event => { event.preventDefault(); open(jobId); }}>
            <label htmlFor="job-id">작업 ID</label><div><Input aria-label="작업 ID" ref={directInput} id="job-id" value={jobId} onChange={event => setJobId(event.target.value)} placeholder="ID로 바로 열기" required /><Button variant="outline" type="submit">조회</Button></div>
          </form>
          <Button id="cleanup-refresh" variant="outline" onClick={refresh} disabled={loading}><ArrowsClockwiseIcon size={16} aria-hidden />목록 새로고침</Button>
        </HStack>
      </header>
      <Card className="jobs-list-card">
        <CardHeader>
          <HStack gap={2} wrap="wrap" className="jobs-list-heading"><CardTitle>작업 목록 <span>{loading ? "…" : catalog.jobs.length}</span></CardTitle><CardDescription>사용자는 현재 소유 사용자 ID 기준입니다. 시각은 한국 시간(KST)입니다.</CardDescription></HStack>
          <HStack gap={2} wrap="wrap" className="jobs-filters">
            <VStack gap={2} className="jobs-search">작업 검색<InputGroup><InputGroupAddon><MagnifyingGlassIcon size={17} aria-hidden /></InputGroupAddon><InputGroupInput aria-label="작업 검색" id="cleanup-query" type="search" value={query} placeholder="제목, 작업 ID, 사용자 ID 검색" onChange={event => { setQuery(event.target.value); resetSelection(); }} /></InputGroup></VStack>
            <div>사용자<NativeSelect aria-label="사용자" id="jobs-owner" value={owner} onChange={event => { setOwner(event.target.value); resetSelection(); }}><option value="">전체 사용자</option><option value="unowned">소유자 없음</option>{owners.map(id => <option value={id} key={id}>{id}</option>)}</NativeSelect></div>
            <div>상태<NativeSelect aria-label="상태" id="cleanup-status" value={status} onChange={event => { setStatus(event.target.value); resetSelection(); }}><option value="">전체 상태</option>{statuses.map(value => <option value={value} key={value}>{jobStatusLabel(value === "unknown" ? undefined : value)}</option>)}</NativeSelect></div>
            <Button variant="ghost" onClick={() => { setQuery(""); setOwner(""); setStatus(""); resetSelection(); }}>초기화</Button>
          </HStack>
        </CardHeader>
        <CardContent>
          {catalogError ? <HStack gap={2} wrap="wrap" role="alert" className="jobs-error"><WarningCircleIcon size={20} aria-hidden /><p>{catalogError}</p><Button variant="outline" onClick={refresh}>목록 다시 조회</Button></HStack>
            : loading ? <p role="status" className="jobs-empty">작업 목록을 불러오는 중…</p>
              : <>
                <HStack gap={2} wrap="wrap" className="jobs-list-summary"><CheckboxInput id="cleanup-select-all" label="현재 페이지 전체 선택" value={visible.length > 0 && visible.every(item => selected.has(item.id))} isDisabled={!visible.length} {...{ disabled: !visible.length }}
                  onChange={checked => setSelected(checked ? new Set(visible.map(item => item.id)) : new Set())} /><HStack gap={2} wrap="wrap" className="jobs-summary-counts"><span>검색 결과 {jobs.length}개</span><span>선택 {selected.size}개</span></HStack></HStack>
                {!visible.length ? <VStack gap={2} className="jobs-empty"><FileTextIcon size={28} aria-hidden /><h3>조회된 작업이 없습니다</h3><p>검색어나 사용자·상태 필터를 변경해 보세요.</p></VStack> : <div id="cleanup-list">
                  <div className="jobs-table-scroll" tabIndex={0} aria-label="작업 목록 표">
                    <Table><caption className="sr-only">작업 목록, 최신 생성 시각순</caption><TableHeader><TableRow><TableHeaderCell>선택</TableHeaderCell><TableHeaderCell>작업 제목</TableHeaderCell><TableHeaderCell>상태</TableHeaderCell><TableHeaderCell>사용자</TableHeaderCell><TableHeaderCell>작업 ID</TableHeaderCell><TableHeaderCell>생성 시각 (KST)</TableHeaderCell><TableHeaderCell><span className="sr-only">상세 조회</span></TableHeaderCell></TableRow></TableHeader>
                      <TableBody>{visible.map(item => <TableRow key={item.id}>
                        <TableCell>{checkbox(item)}</TableCell><TableCell className="jobs-title-cell"><Button type="button" className="jobs-title" onClick={() => open(item.id)}>{item.request || "제목 없는 작업"}</Button></TableCell>
                        <TableCell><JobStatus status={item.status} /></TableCell><TableCell><RecordId value={item.owner_id} /></TableCell><TableCell><RecordId value={item.id} /></TableCell><TableCell className="jobs-time">{jobTime(item.created_at)}</TableCell>
                        <TableCell><Button variant="ghost" onClick={() => open(item.id)}>상세 조회<ArrowRightIcon size={14} aria-hidden /></Button></TableCell>
                      </TableRow>)}</TableBody>
                    </Table>
                  </div>
                  <div className="jobs-mobile-list" role="list" aria-label="작업 카드 목록">{visible.map(item => <article role="listitem" className="jobs-mobile-item" key={item.id}>
                    <HStack gap={2} wrap="wrap" className="jobs-mobile-heading">{checkbox(item)}<JobStatus status={item.status} /></HStack>
                    <Button type="button" className="jobs-title" onClick={() => open(item.id)}>{item.request || "제목 없는 작업"}</Button>
                    <dl><div><dt><UserCircleIcon size={14} aria-hidden />사용자</dt><dd><RecordId value={item.owner_id} /></dd></div><div><dt>작업 ID</dt><dd><RecordId value={item.id} /></dd></div><div><dt>생성 시각</dt><dd>{jobTime(item.created_at)}</dd></div></dl>
                    <Button variant="outline" onClick={() => open(item.id)}>상세 조회<ArrowRightIcon size={14} aria-hidden /></Button>
                  </article>)}</div>
                </div>}
                <HStack gap={2} wrap="wrap" className="jobs-pagination"><HStack gap={2} wrap="wrap" className="jobs-summary-counts"><span>{jobs.length ? `${page * PAGE_SIZE + 1}–${Math.min((page + 1) * PAGE_SIZE, jobs.length)} / ${jobs.length}개` : "0개"}</span><span>최신 생성 시각순</span></HStack><div>
                  <Button variant="outline" disabled={page === 0} onClick={() => { setPage(value => value - 1); setSelected(new Set()); }}>이전</Button>
                  <Button variant="outline" disabled={(page + 1) * PAGE_SIZE >= jobs.length} onClick={() => { setPage(value => value + 1); setSelected(new Set()); }}>다음</Button>
                </div></HStack>
              </>}
        </CardContent>
      </Card>
      <VStack gap={2} className="jobs-management">
        <Card><CardHeader><CardTitle id="cleanup-title">데이터 정리</CardTitle><CardDescription>삭제할 기록을 미리 확인한 뒤 정리합니다.</CardDescription></CardHeader><CardContent>
          <HStack gap={2} wrap="wrap" className="jobs-selection"><span><strong>{selected.size}개</strong> 작업 선택됨</span><Button id="cleanup-selected" variant="outline" disabled={!selected.size || loading || !!catalogError} onClick={() => void preview("jobs")}><TrashIcon size={16} aria-hidden />선택 작업 삭제 미리보기</Button></HStack>
          <div id="cleanup-pending">{catalog.pending.map(id => <Button key={id} variant="outline" disabled={loading || !!catalogError} onClick={() => void execute(id, "")}><ArrowsClockwiseIcon size={16} aria-hidden />남은 파일 정리 재시도 <span>{id}</span></Button>)}</div>
          <details className="jobs-danger"><summary><ShieldWarningIcon size={17} aria-hidden />전체 기록 삭제</summary><p>모든 작업과 저장된 기록을 영구 삭제합니다. 미리보기에서 대상을 확인하세요.</p><Button id="cleanup-all" variant="outline" disabled={loading || !!catalogError} onClick={() => void preview("all")}>전체 기록 삭제 미리보기</Button></details>
        </CardContent></Card>
      </VStack>
    </fieldset>
    {error && <p className="jobs-error" role="alert">{error}</p>}
    <p id="cleanup-notice" role="status">{notice}</p>
    <JobDetailSheet id={linkedId} job={job} fallback={catalog.jobs.find(item => item.id === linkedId)} loading={jobLoading} error={jobError}
      tab={tab} setTab={setTab} close={close} retry={() => setRetry(value => value + 1)}
      restoreFocus={() => { if (opener.current?.isConnected) opener.current.focus(); else directInput.current?.focus(); }} />
    <Dialog open={!!operation} onOpenChange={open => { if (!open && !disabled) setOperation(null); }}>
    {operation && <DialogContent id="cleanup-dialog" className="jobs-cleanup-dialog" showCloseButton={false} onKeyDown={event => { if (disabled && event.key === "Escape") event.preventDefault(); }}>
      <DialogTitle><ShieldWarningIcon size={20} aria-hidden /> 영구 삭제 확인</DialogTitle>
      <div id="cleanup-summary"><dl className="jobs-cleanup-summary"><div><dt>대상 작업</dt><dd>{operation.counts.jobs}개</dd></div><div><dt>파일</dt><dd>{operation.counts.files || 0}개</dd></div><div><dt>제거할 다른 작업의 출처 연결</dt><dd>{operation.external_references || 0}개</dd></div><div><dt>신규 재사용이 중단되는 공통 결정</dt><dd>{operation.counts.project_decisions || 0}개</dd></div><div><dt>제외 폴더</dt><dd>{(operation.skipped || []).length}개</dd></div></dl><h3>삭제 대상</h3><ul className="jobs-cleanup-targets">{(operation.targets || [...selected]).map(id => <li key={id}>{id}</li>)}</ul><DialogDescription>삭제한 기록은 복구할 수 없습니다. 미리보기는 10분 동안 유효합니다.</DialogDescription></div>
      {operation.scope === "all" && <div id="cleanup-confirm-label">계속하려면 “전체 기록 삭제”를 입력하세요.<Input aria-label="계속하려면 “전체 기록 삭제”를 입력하세요." id="cleanup-confirm" value={confirmation} autoComplete="off" onChange={event => setConfirmation(event.target.value)} disabled={disabled} /></div>}
      <p id="cleanup-error" role="alert">{cleanupError}</p><HStack gap={2} wrap="wrap" className="jobs-dialog-actions"><Button ref={cleanupCancel} id="cleanup-cancel" variant="outline" autoFocus disabled={disabled} onClick={() => setOperation(null)}>취소</Button>
        <Button id="cleanup-execute" variant="destructive" disabled={disabled || (operation.scope === "all" && confirmation !== "전체 기록 삭제")} onClick={() => void execute(operation.id)}>영구 삭제</Button>
      </HStack>
    </DialogContent>}
    </Dialog>
  </VStack>;
}
