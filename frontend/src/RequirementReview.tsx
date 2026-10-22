import { Fragment, useEffect, useId, useState } from "react";
import { CaretDownIcon, LinkIcon, ListChecksIcon, MagnifyingGlassIcon, TestTubeIcon } from "@phosphor-icons/react";
import { api } from "./api";
import { Button } from "./UI";
import { Badge } from "./components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "./components/ui/collapsible";
import { Popover, PopoverContent, PopoverTrigger } from "./components/ui/popover";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "./components/ui/table";
import { InputGroup, InputGroupInput, InputGroupAddon } from "./components/ui/input-group";
import { NativeSelect, NativeSelectOption } from "./components/ui/native-select";
import { Pagination, PaginationContent, PaginationItem } from "./components/ui/pagination";
import { Alert, AlertDescription } from "./components/ui/alert";
import { Empty, EmptyHeader, EmptyTitle, EmptyDescription } from "./components/ui/empty";
import { Skeleton } from "./components/ui/skeleton";
import "./requirement-review.css";

export type RequirementEvidence = { item_id: string; section: string; quote: string; start: number; end: number; line: number; shared: boolean; provenance: string; truncated?: boolean; category?: string };
type EvidenceColumn = "specification" | "acceptance" | "verification";
type ReviewRow = { id: string; text: string; group: string; spec_status: string; acceptance_status: string; verification_status: string; test_status: "not_collected"; specification: RequirementEvidence[]; acceptance: RequirementEvidence[]; verification: RequirementEvidence[]; specification_total: number; acceptance_total: number; verification_total: number };
export type RequirementReviewData = { status: "ready" | "limited" | "unavailable"; message: string; basis?: { id: string; source_hash: string }; review_status?: string; summary?: { total: number; spec_linked: number; acceptance_linked: number; verification_linked: number }; rows: ReviewRow[]; unlinked: RequirementEvidence[]; unlinked_total: number; evidence?: RequirementEvidence[]; requirement?: { text: string }; total: number; has_more: boolean; offset: number };
const groups: Record<string, string> = { mandatory_requirements: "필수", recommended_requirements: "권장", optional_requirements: "선택", constraints: "제약", non_scope: "비범위" };
const sections: Record<string, string> = { acceptance_criteria: "인수 조건", test_plan: "테스트 계획", manual_verification_checklist: "수동 확인 절차" };
const columns: [EvidenceColumn, string][] = [["specification", "반영된 명세"], ["acceptance", "인수 조건"], ["verification", "검증 방법"]];

function PageControls({ offset, more, busy, onPage, label }: { offset: number; more: boolean; busy: boolean; onPage: (offset: number) => void; label: string }) {
  return <Pagination aria-label={label}><PaginationContent><PaginationItem><Button disabled={!offset || busy} onClick={() => onPage(offset - 20)}>이전</Button></PaginationItem><PaginationItem><span aria-live="polite">{offset / 20 + 1}페이지</span></PaginationItem><PaginationItem><Button disabled={!more || busy} onClick={() => onPage(offset + 20)}>다음</Button></PaginationItem></PaginationContent></Pagination>;
}

type Locate = (ref: RequirementEvidence) => void;

function Citation({ evidence, onLocate }: { evidence: RequirementEvidence; onLocate?: Locate }) {
  return <Popover><PopoverTrigger asChild><Button className="rr-citation"><LinkIcon size={14} aria-hidden />{sections[evidence.section] || evidence.section} · {evidence.line}행</Button></PopoverTrigger><PopoverContent className="rr-popover"><p>{evidence.provenance === "recorded_block" ? "기록된 블록 연결" : "섹션 원문 · 요구사항 연결 미확인"}{evidence.shared && " · 공통 근거"}</p><blockquote>{evidence.quote}</blockquote>{evidence.truncated && <p>원문의 일부입니다. 전체 내용은 명세에서 확인하세요.</p>}{onLocate && <Button onClick={() => onLocate(evidence)}>명세 원문 위치로 이동</Button>}</PopoverContent></Popover>;
}
function Details({ requirement, base, stepId, basisId, onLocate }: { requirement: string; base: string; stepId?: string; basisId?: string; onLocate?: Locate }) {
  const [open, setOpen] = useState(false), [page, setPage] = useState(0), [result, setResult] = useState<RequirementReviewData | null>(null), [pending, setPending] = useState(false), [failure, setFailure] = useState("");
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController(); setPending(true); setFailure(""); setResult(null);
    const search = new URLSearchParams({ ...(stepId ? { step_id: stepId } : {}), offset: String(page) }); search.set("evidence_for", requirement);
    void (async () => {
      try {
        const value = await api<RequirementReviewData>(`${base}?${search}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (value.basis?.id !== basisId) throw new Error("기준 자료가 변경되었습니다. 근거표를 다시 조회하세요.");
        setResult(value);
      } catch (e) { if (!controller.signal.aborted) setFailure((e as Error).message); }
      finally { if (!controller.signal.aborted) setPending(false); }
    })();
    return () => controller.abort();
  }, [open, page, base, stepId, basisId, requirement]);
  return <Collapsible open={open} onOpenChange={setOpen}><CollapsibleTrigger className="rr-expand">{requirement === "__unlinked__" ? "미연결 원문 전체 보기" : `${requirement} 연결 근거 전체 보기`}<CaretDownIcon size={15} aria-hidden /></CollapsibleTrigger><CollapsibleContent>{pending && <p role="status">원문 근거 조회 중</p>}{failure && <Alert role="alert"><AlertDescription>{failure}</AlertDescription></Alert>}{result?.evidence?.map((e, i) => <article className="rr-evidence" key={`${e.start}:${i}`}><Badge variant="outline">{columns.find(c => c[0] === e.category)?.[1] || "미연결 원문"}</Badge>{e.shared && <Badge variant="secondary">공통 근거</Badge>}<blockquote>{e.quote}</blockquote><Citation evidence={e} onLocate={onLocate} /></article>)}{result && !result.total && <p>연결 근거를 확인하지 못했습니다.</p>}{result && <PageControls offset={page} more={result.has_more} busy={pending} onPage={setPage} label={`${requirement} 근거 페이지`} />}</CollapsibleContent></Collapsible>;
}
function EvidenceCell({ row, kind, onLocate }: { row: ReviewRow; kind: EvidenceColumn; onLocate?: Locate }) {
  const refs = row[kind];
  return <div className="rr-cell"><Badge variant={refs.length ? "secondary" : "outline"}>{refs.length ? kind === "specification" ? "근거 연결됨" : "작성 근거 연결됨" : "연결 확인 필요"}</Badge>{refs.map(e => <div key={e.start}><p>{e.quote}{e.truncated && "…"}</p>{e.shared && <small>공통 근거</small>}<Citation evidence={e} onLocate={onLocate} /></div>)}{row[`${kind}_total`] > 1 && <small>총 {row[`${kind}_total`]}개 · 전체 근거에서 확인</small>}</div>;
}

export function RequirementReview({ jobId, stepId, sourceHash, compact = false, onOpen, onLocate, onQuestion }: { jobId: string; stepId?: string; sourceHash?: string; compact?: boolean; onOpen?: () => void; onLocate?: (ref: RequirementEvidence) => void; onQuestion?: (question: string) => void }) {
  const [data, setData] = useState<RequirementReviewData | null>(null), [loading, setLoading] = useState(true), [error, setError] = useState("");
  const [offset, setOffset] = useState(0), [query, setQuery] = useState(""), [filter, setFilter] = useState("all"), [retry, setRetry] = useState(0);
  const id = useId();
  const base = `/api/jobs/${encodeURIComponent(jobId)}/requirement-review`;
  const params = (page = 0) => new URLSearchParams({ ...(stepId ? { step_id: stepId } : {}), offset: String(page) });
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(""); setData(null);
    const search = params(offset); search.set("query", compact ? "" : query); search.set("missing", String(!compact && filter === "missing"));
    void (async () => {
      try {
        const value = await api<RequirementReviewData>(`${base}?${search}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (sourceHash && value.basis && sourceHash !== value.basis.source_hash) throw new Error("기준 문서가 다릅니다. 이 명세를 다시 열어주세요.");
        setData(value);
      } catch (failure) { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : "근거표를 불러오지 못했습니다."); }
      finally { if (!controller.signal.aborted) setLoading(false); }
    })();
    return () => controller.abort();
  }, [jobId, stepId, sourceHash, offset, query, filter, retry, compact]);
  const question = (r: ReviewRow) => `${r.id} 요구사항의 명세 반영 근거, 인수 조건, 검증 방법 중 연결이 확인되지 않은 부분을 확인하고 명세에서 연결해 주세요.`;
  return <section className={`requirement-review${compact ? " rr-compact" : ""}`} aria-labelledby={`${id}-title`}>
    <header className="rr-header"><div><span className="rr-eyebrow"><ListChecksIcon size={16} aria-hidden />문서 근거 확인</span><h3 id={`${id}-title`}>요구사항별 검토 근거</h3><p>문서에 적힌 내용과 실제 테스트 결과를 구분합니다.</p></div>{compact && onOpen && <Button onClick={onOpen}>전체 근거 보기</Button>}</header>
    {!compact && <div className="rr-filters"><InputGroup><InputGroupAddon><MagnifyingGlassIcon size={17} aria-hidden /></InputGroupAddon><InputGroupInput aria-label="요구사항 검색" maxLength={200} placeholder="요구사항 ID 또는 내용 검색" value={query} onChange={e => { setQuery(e.target.value); setOffset(0); }} /></InputGroup><NativeSelect aria-label="요구사항 연결 필터" value={filter} onChange={e => { setFilter(e.target.value); setOffset(0); }}><NativeSelectOption value="all">전체 요구사항</NativeSelectOption><NativeSelectOption value="missing">연결 확인 필요</NativeSelectOption></NativeSelect></div>}
    {loading ? <div role="status" aria-label="요구사항 근거 조회 중"><Skeleton className="h-12 w-full" /></div> : error ? <Alert role="alert"><AlertDescription>{error}</AlertDescription><Button onClick={() => setRetry(v => v + 1)}>근거표 다시 조회</Button></Alert> : data?.status === "unavailable" ? <Empty><EmptyHeader><EmptyTitle>검토 근거 준비 전</EmptyTitle><EmptyDescription>{data.message}</EmptyDescription></EmptyHeader></Empty> : data && <>
      <div className="rr-summary" aria-label="전체 요구사항 연결 요약"><Badge variant="secondary">명세 근거 연결 {data.summary?.spec_linked}/{data.summary?.total}</Badge><Badge variant="secondary">인수 조건 연결 {data.summary?.acceptance_linked}/{data.summary?.total}</Badge><Badge variant="secondary">검증 방법 연결 {data.summary?.verification_linked}/{data.summary?.total}</Badge><Badge variant="outline"><TestTubeIcon size={14} aria-hidden />실제 테스트 결과 미수집</Badge></div>
      <p className="rr-review-status">{data.review_status === "pending_approval" ? "명세 문서 검토 통과 · 사용자 승인 대기" : data.review_status === "approved" ? "명세 문서 검토 통과 · 사용자 승인 완료" : "해당 시점의 문서 검토 결과 확인 자료 부족"}</p>
      {data.status === "limited" && <Alert><AlertDescription>요구사항별 연결 자료 부족 · 남아 있는 섹션 원문을 제공합니다. 연결 미확인이 본문 부재를 뜻하지 않습니다.</AlertDescription></Alert>}
      <p className="rr-limit">{data.message} 인수 조건과 검증 방법의 일대일 대응은 별도로 확인해야 합니다.</p>
      {!compact && <>
        {!data.rows.length && <Empty><EmptyHeader><EmptyTitle>표시할 요구사항이 없습니다</EmptyTitle><EmptyDescription>검색 조건 또는 이력의 연결 자료를 확인하세요.</EmptyDescription></EmptyHeader></Empty>}
        {[[false, "요구사항"], [true, "비범위 항목"]].map(([excluded, title]) => {
          const rows = data.rows.filter(r => (r.group === "non_scope") === excluded);
          return rows.length ? <section className="rr-group" key={String(title)}><h4>{title}</h4>{excluded && <p className="rr-limit">비범위 항목은 구현·검증 계획 연결 집계에 포함하지 않습니다.</p>}<Table><TableCaption>기록된 문서 연결 · 구현 테스트 통과 여부를 나타내지 않습니다.</TableCaption><TableHeader><TableRow><TableHead>요구사항</TableHead>{columns.map(c => <TableHead key={c[0]}>{c[1]}</TableHead>)}<TableHead>실제 테스트</TableHead></TableRow></TableHeader><TableBody>{rows.map(row => <Fragment key={row.id}><TableRow><TableCell data-label="요구사항"><div className="rr-requirement"><Badge variant="outline">{groups[row.group]}</Badge><strong>{row.id}</strong><p>{row.text}</p>{onQuestion && row.group !== "non_scope" && [row.spec_status, row.acceptance_status, row.verification_status].includes("unconfirmed") && <Button onClick={() => onQuestion(question(row))}>수정 의견에 추가</Button>}</div></TableCell>{columns.map(([kind, label]) => <TableCell key={kind} data-label={label}><EvidenceCell row={row} kind={kind} onLocate={onLocate} /></TableCell>)}<TableCell data-label="실제 테스트"><Badge variant="outline">결과 미수집</Badge></TableCell></TableRow><TableRow className="rr-details-row"><TableCell colSpan={5}><Details requirement={row.id} base={base} stepId={stepId} basisId={data.basis?.id} onLocate={onLocate} /></TableCell></TableRow></Fragment>)}</TableBody></Table></section> : null;
        })}
        {!!data.unlinked_total && <section className="rr-unlinked"><h4>요구사항 연결이 없는 인수 조건·검증 방법 · {data.unlinked_total}개</h4><p>연결이 없어도 원문을 보존합니다. 어떤 요구사항을 검증하는지 확인하세요.</p><Details requirement="__unlinked__" base={base} stepId={stepId} basisId={data.basis?.id} onLocate={onLocate} /></section>}
        <PageControls offset={offset} more={data.has_more} busy={loading} onPage={setOffset} label="요구사항 근거 페이지" />
      </>}
    </>}
  </section>;
}
