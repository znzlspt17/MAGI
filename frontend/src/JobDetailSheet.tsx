import { useState } from "react";
import { CopyIcon, WarningCircleIcon } from "@phosphor-icons/react";
import { Button } from "./components/ui/button";
import { Badge } from "./components/ui/badge";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "./components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";
import { Markdown, statusLabel } from "./UI";
import { jobTime, type JobDetail, type JobRecord } from "./job-data";

export function RecordId({ value }: { value?: string | null }) {
  const [notice, setNotice] = useState("");
  if (!value) return <span className="jobs-muted">미지정</span>;
  return <span className="jobs-id">
    <code title={value}>{value.length > 18 ? value.slice(0, 8) + "…" + value.slice(-6) : value}</code>
    <button type="button" aria-label={`${value} 복사`} title={`${value} 복사`} onClick={async () => {
      try { await navigator.clipboard.writeText(value); setNotice("복사됨"); }
      catch { setNotice("복사하지 못했습니다."); }
    }}><CopyIcon size={14} aria-hidden /></button>
    <span className="jobs-copy-result" role="status">{notice}</span>
  </span>;
}

export function JobStatus({ status }: { status?: string | null }) {
  const tone = ["FINALIZED", "completed"].includes(status || "") ? "success"
    : ["error", "failed", "blocked", "CRITICAL_BLOCKED"].includes(status || "") ? "error"
    : ["NEEDS_USER_INPUT", "waiting", "waiting_approval", "PASS_PENDING_USER_APPROVAL", "needs_revision", "REJECTED_BY_USER"].includes(status || "") ? "waiting"
    : ["running", "queued", "ANALYZING", "COMPILING", "CRITIQUING", "RESEARCHING"].includes(status || "") ? "active" : "neutral";
  return <Badge variant="outline" className={`jobs-status jobs-status-${tone}`}>
    <span aria-hidden />{jobStatusLabel(status)}
  </Badge>;
}

export function jobStatusLabel(status?: string | null) {
  const labels: Record<string, string> = {
    ANALYZING: "분석 중", APPROVED: "승인됨", COMPILING: "명세 작성 중",
    CRITIQUING: "검토 중", DRAFT: "초안 작성됨", REJECTED_BY_USER: "사용자 반려", RESEARCHING: "자료 조사 중",
  };
  return labels[status || ""] || statusLabel(status || undefined);
}

export default function JobDetailSheet({ id, job, fallback, loading, error, tab, setTab, close, retry, restoreFocus }: {
  id: string; job: JobDetail | null; fallback?: JobRecord; loading: boolean; error: string;
  tab: string; setTab: (value: string) => void; close: () => void; retry: () => void; restoreFocus: () => void;
}) {
  const value = job || fallback;
  return <Sheet open={!!id} onOpenChange={open => { if (!open) close(); }}>
    <SheetContent className="jobs-detail" onCloseAutoFocus={event => { event.preventDefault(); restoreFocus(); }}>
      <SheetHeader>
        <span className="jobs-eyebrow">JOB DETAILS</span>
        <SheetTitle>작업 상세</SheetTitle>
        <SheetDescription>요청 내용, 생성된 문서와 처리 이력을 확인합니다.</SheetDescription>
        <div className="jobs-detail-heading"><RecordId value={id} />{value && <JobStatus status={value.status} />}</div>
      </SheetHeader>
      <div className="jobs-detail-body" id="job-result" aria-label="작업 상세 내용" aria-busy={loading}>
        {loading ? <p className="jobs-empty" role="status">작업을 조회하는 중…</p> : error ?
          <div className="jobs-error" role="alert"><WarningCircleIcon size={20} aria-hidden /><p>{error}</p><Button variant="outline" onClick={retry}>다시 조회</Button></div>
          : job && <Tabs value={tab} onValueChange={setTab}>
            <TabsList aria-label="작업 상세 탭" className="jobs-detail-tabs">
              <TabsTrigger value="summary">요약</TabsTrigger><TabsTrigger value="final">최종 명세</TabsTrigger>
              <TabsTrigger value="candidate">초안</TabsTrigger><TabsTrigger value="critical">보완 보고서</TabsTrigger>
              <TabsTrigger value="history">처리 이력</TabsTrigger>
            </TabsList>
            <TabsContent value="summary">
              <dl className="jobs-detail-meta">
                <div><dt>사용자 · 현재 소유자</dt><dd><RecordId value={job.owner_id === undefined ? fallback?.owner_id : job.owner_id} /></dd></div>
                <div><dt>상태</dt><dd><JobStatus status={job.status} /></dd></div>
                <div><dt>생성 시각 (KST)</dt><dd>{jobTime(job.created_at || fallback?.created_at)}</dd></div>
              </dl>
              <h3>전체 요청 내용</h3><p className="jobs-full-request">{job.request || fallback?.request || "저장된 요청 내용이 없습니다."}</p>
            </TabsContent>
            {([ ["final", "최종 명세"], ["candidate", "초안"], ["critical", "보완 보고서"] ] as const).map(([key, label]) =>
              <TabsContent value={key} key={key}>
                {job[key]?.trim() ? <Markdown content={job[key]!} /> : <p className="jobs-empty">저장된 {label}{key === "candidate" ? "이" : "가"} 없습니다.</p>}
              </TabsContent>,
            )}
            <TabsContent value="history">
              {job.session_events?.length ? <ol className="jobs-history">{job.session_events.map((event, index) =>
                <li key={index}><span className="jobs-history-number">{index + 1}</span><div><strong>{event.action || "처리 기록"}</strong><p>{jobStatusLabel(event.status)}</p></div></li>,
              )}</ol> : <p className="jobs-empty">저장된 처리 이력이 없습니다.</p>}
            </TabsContent>
          </Tabs>}
      </div>
    </SheetContent>
  </Sheet>;
}
