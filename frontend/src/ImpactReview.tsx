import { useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowRightIcon, LinkIcon, SparkleIcon, WarningCircleIcon, CircleNotchIcon } from "@phosphor-icons/react";
import { api, post } from "./api";
import { useAuth } from "./Auth";
import { PromptInput } from "./components/PromptInput";
import { Button } from "./components/ui/button";
import { Badge } from "./components/ui/badge";
import { Field, FieldLabel, FieldDescription, FieldError } from "./components/ui/field";
import { NativeSelect, NativeSelectOption } from "./components/ui/native-select";
import { Item, ItemGroup, ItemContent, ItemTitle, ItemDescription } from "./components/ui/item";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "./components/ui/collapsible";
import { Trace, TraceLine, TraceTitle, TraceIcon, TraceCollapsible, TraceCollapsibleTrigger, TraceCollapsibleContent } from "./components/ui/trace";
import { Popover, PopoverTrigger, PopoverContent } from "./components/ui/popover";
import { Empty, EmptyHeader, EmptyTitle, EmptyDescription } from "./components/ui/empty";
import { Alert, AlertTitle, AlertDescription } from "./components/ui/alert";
import { Pagination, PaginationContent, PaginationItem } from "./components/ui/pagination";
import { Skeleton } from "./components/ui/skeleton";
import "./impact-review.css";

export type ImpactNode = { id: string; kind: string; body: string; section: string; requirement_id: string };
export type ImpactBasis = { id: string; job_id: string; source_hash: string; node_id: string | null; status: string };
export type RecordedImpact = { target: ImpactNode; path_total?: number; paths: { kind: "direct" | "spec_review" | "shared_decision"; nodes: ImpactNode[] }[] };
export type ImpactPage = { basis: ImpactBasis; node: ImpactNode | null; recorded: RecordedImpact[]; total: number; offset: number; has_more: boolean; next_offset: number; message: string };
export type InferredImpact = { topic: string; effect: string; rationale: string; question: string; evidence: { node_id: string; quote: string }[] };
export type ImpactReport = { id: string; status: "running" | "complete" | "failed" | "interrupted"; basis: ImpactBasis; stale: boolean; reason?: string;
  proposal: string; change_kind: string; inferred: InferredImpact[]; limitations: string[];
  coverage: { total: number; included: number; omitted: number; truncated: number; recorded_total: number; recorded_included: number };
  sources: { node_id: string; kind: string; text: string; section: string }[] };

const pathLabels = { direct: "직접 연결", spec_review: "연결 명세의 검토", shared_decision: "공유 설계 결정" };
const nodeLabel = (node: ImpactNode) => node.requirement_id || node.section || ({ requirement: "요구사항", decision: "설계 결정", review: "검토 항목", spec: "명세" }[node.kind] || "항목");

function ImpactCitation({ evidence, report, inspect }: { evidence: InferredImpact["evidence"][number]; report: ImpactReport; inspect: (id: string) => void }) {
  const source = report.sources.find(item => item.node_id === evidence.node_id);
  return <Popover><PopoverTrigger asChild><Button variant="secondary" size="sm" className="impact-citation">{source?.section || "근거 원문"}</Button></PopoverTrigger>
    <PopoverContent className="impact-citation-content" onEscapeKeyDown={event => event.stopPropagation()}>
      <strong>판단에 사용한 원문</strong><blockquote>{evidence.quote}</blockquote>
      <Button variant="outline" size="sm" onClick={() => inspect(evidence.node_id)}>항목 원문 열기<ArrowRightIcon aria-hidden /></Button>
    </PopoverContent></Popover>;
}

export function ImpactReview({ jobId, nodeId, inspect }: { jobId: string; nodeId?: string; inspect: (id: string) => void }) {
  const { user, status } = useAuth();
  const navigate = useNavigate(), id = useId();
  const [kind, setKind] = useState(nodeId ? "modify" : "add");
  const [proposal, setProposal] = useState("");
  const [page, setPage] = useState<ImpactPage | null>(null);
  const [report, setReport] = useState<ImpactReport | null>(null);
  const [loading, setLoading] = useState(true), [analysing, setAnalysing] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0), alive = useRef(true), sending = useRef(false);
  const selectedId = kind === "add" ? undefined : nodeId;
  const blocked = status.ready === false || status.checkState === "error";

  async function load(offset = 0) {
    const ticket = ++generation.current;
    setLoading(true); setError("");
    try {
      const query = new URLSearchParams({ job_id: jobId, offset: String(offset) });
      if (selectedId) query.set("node_id", selectedId);
      const data = await api<ImpactPage>("/api/knowledge/impact?" + query);
      if (alive.current && ticket === generation.current) {
        setPage(data);
        setReport(previous => previous?.basis.id === data.basis.id ? previous : null);
      }
    } catch (failure) {
      if (alive.current && ticket === generation.current) {
        setPage(null); setError(failure instanceof Error ? failure.message : "연결을 조회하지 못했습니다.");
      }
    } finally {
      if (alive.current && ticket === generation.current) setLoading(false);
    }
  }
  useEffect(() => {
    alive.current = true;
    sending.current = false; setAnalysing(false);
    setPage(null); setReport(null);
    void load();
    return () => { alive.current = false; generation.current++; };
  }, [jobId, selectedId]);

  async function analyse() {
    if (sending.current || blocked || loading || !page) return;
    if (!proposal.trim() || proposal.length > 4000) { setError("변경 가정을 1~4000자로 입력하세요."); return; }
    sending.current = true;
    setAnalysing(true); setError("");
    const ticket = ++generation.current;
    try {
      const result = await post<ImpactReport>("/api/knowledge/impact", { job_id: jobId, node_id: selectedId || null,
        change_kind: kind, proposal: proposal.trim(), basis_id: page.basis.id });
      if (alive.current && ticket === generation.current) setReport(result);
    } catch (failure) {
      if (alive.current && ticket === generation.current) setError(failure instanceof Error ? failure.message : "추가 영향 분석을 완료하지 못했습니다.");
    } finally {
      if (alive.current && ticket === generation.current) { sending.current = false; setAnalysing(false); }
    }
  }
  function addQuestion(question: string) {
    const key = `draft:${user?.id || "local"}:${jobId}:feedback`;
    const existing = sessionStorage.getItem(key)?.trim();
    const text = `변경 가정: ${report?.proposal || proposal}\n확인할 사항: ${question}`;
    sessionStorage.setItem(key, existing ? `${existing}\n\n${text}` : text);
    navigate(`/jobs/${jobId}`);
  }
  const sources = report ? [...new Map(report.inferred.flatMap(item => item.evidence).map(ref => [ref.node_id, ref])).values()] : [];

  return <section className="impact-review" aria-labelledby={`${id}-title`} onKeyDown={event => { if (event.key === "Escape") event.stopPropagation(); }}>
    <header><span className="impact-eyebrow">변경 전 검토</span><h3 id={`${id}-title`}>바꾸기 전에 살펴보세요</h3><p>기록된 연결과 추가 검토 제안을 나누어 확인합니다. 명세에는 아직 반영되지 않습니다.</p></header>
    <Field><FieldLabel htmlFor={`${id}-kind`}>변경 종류</FieldLabel>
      <NativeSelect id={`${id}-kind`} value={kind} disabled={analysing} onChange={event => { setKind(event.target.value); setReport(null); }}>
        {nodeId && <><NativeSelectOption value="modify">요구사항 변경</NativeSelectOption><NativeSelectOption value="remove">요구사항 삭제</NativeSelectOption></>}
        <NativeSelectOption value="add">새 요구사항 추가</NativeSelectOption>
      </NativeSelect>
    </Field>
    <Field data-invalid={!!error}><FieldLabel htmlFor={`${id}-proposal`}>변경 가정</FieldLabel>
      <PromptInput id={`${id}-proposal`} label="변경 가정" buttonLabel={analysing ? "추가 영향 분석 중" : "추가 영향 분석"} maxLength={4000} rows={3}
        value={proposal} onChange={event => { setProposal(event.target.value); setReport(null); }} readOnly={analysing} disabled={loading || analysing || blocked || !page}
        placeholder="예: 네트워크 연결 없이도 기록을 작성할 수 있게 해줘"
        aria-describedby={`${id}-help${error ? ` ${id}-error` : ""}`} aria-invalid={!!error} onSend={() => void analyse()} />
      <FieldDescription id={`${id}-help`}>기록된 연결 조회에는 모델을 사용하지 않습니다. 추가 영향 분석을 실행하면 사용 비용이 발생할 수 있습니다. {proposal.length}/4,000자</FieldDescription>
      {error && <FieldError id={`${id}-error`}>{error}</FieldError>}
    </Field>
    <Trace aria-label="영향 검토 처리 상태"><TraceLine status={loading || analysing ? "running" : error ? "error" : undefined}>
      <TraceIcon>{loading || analysing ? <CircleNotchIcon className="animate-spin" /> : <LinkIcon />}</TraceIcon>
      <TraceTitle><span role="status">{loading ? "기록된 연결 조회 중" : analysing ? "추가 영향 분석 중" : page ? "기록된 연결 조회 완료" : "기록된 연결 조회 불가"}</span></TraceTitle>
    </TraceLine></Trace>
    <Button variant="outline" size="sm" disabled={loading || analysing} onClick={() => void load()}>기준 다시 조회</Button>
    <section className="impact-section" aria-labelledby={`${id}-recorded`}>
      <h4 id={`${id}-recorded`}><LinkIcon aria-hidden />기록으로 연결된 검토 대상 <Badge variant="secondary">기록된 연결</Badge></h4>
      {loading ? <div aria-label="연결 조회 중"><Skeleton className="h-12 w-full" /><Skeleton className="h-12 w-full" /></div> : page ? <>
        <p className="impact-help">{page.message}</p>
        {page.recorded.length ? <ItemGroup>{page.recorded.map(item => <Item key={item.target.id} variant="outline" size="sm"><ItemContent>
          <ItemTitle>{nodeLabel(item.target)}</ItemTitle><ItemDescription>{item.target.body}</ItemDescription>
          <Collapsible><CollapsibleTrigger asChild><Button variant="ghost" size="sm">관계 경로 확인</Button></CollapsibleTrigger><CollapsibleContent>
            {(item.path_total || 0) > item.paths.length && <p className="impact-help">기록된 경로 {item.path_total}개 중 {item.paths.length}개를 표시합니다. 경로의 항목을 열어 추가 관계를 확인할 수 있습니다.</p>}
            {item.paths.map((path, index) => <Trace key={index}><TraceLine><TraceTitle>{pathLabels[path.kind]}</TraceTitle></TraceLine>
              {path.nodes.map((node, step) => <TraceLine key={node.id}><TraceTitle><Button variant="link" size="sm" onClick={() => inspect(node.id)}>{step + 1}. {nodeLabel(node)}</Button></TraceTitle></TraceLine>)}
            </Trace>)}
          </CollapsibleContent></Collapsible>
          <Button variant="outline" size="sm" onClick={() => inspect(item.target.id)}>항목 원문 열기<ArrowRightIcon aria-hidden /></Button>
        </ItemContent></Item>)}</ItemGroup> : <Empty><EmptyHeader><EmptyTitle>기록된 연결을 찾지 못했습니다</EmptyTitle><EmptyDescription>연결이 없어도 다른 명세에 영향이 있을 수 있습니다. 변경 가정을 입력해 추가로 검토할 수 있습니다.</EmptyDescription></EmptyHeader></Empty>}
        {page.total > 20 && <Pagination aria-label="기록된 검토 대상 페이지"><PaginationContent>
          <PaginationItem><Button variant="outline" size="sm" disabled={page.offset === 0 || analysing} onClick={() => void load(page.offset - 20)}>이전</Button></PaginationItem>
          <PaginationItem><span>{Math.floor(page.offset / 20) + 1} / {Math.ceil(page.total / 20)}</span></PaginationItem>
          <PaginationItem><Button variant="outline" size="sm" disabled={!page.has_more || analysing} onClick={() => void load(page.next_offset)}>다음</Button></PaginationItem>
        </PaginationContent></Pagination>}
      </> : <Alert><WarningCircleIcon aria-hidden /><AlertTitle>기준 명세를 확인하세요</AlertTitle><AlertDescription>승인 후보가 준비된 작업에서 현재 요구사항을 선택해 주세요.</AlertDescription></Alert>}
    </section>
    <section className="impact-section" aria-labelledby={`${id}-inferred`}>
      <h4 id={`${id}-inferred`}><SparkleIcon aria-hidden />모델이 제안한 추가 검토 <Badge variant="outline">모델 추정</Badge></h4>
      {!report ? <p className="impact-help">변경 가정을 입력하고 추가 영향 분석을 실행하면 검토 후보가 여기에 표시됩니다.</p> : <>
        {(report.stale || report.status !== "complete") && <Alert><WarningCircleIcon aria-hidden /><AlertTitle>{report.stale ? "이전 기준의 분석 결과입니다" : "분석을 완료하지 못했습니다"}</AlertTitle><AlertDescription>{report.stale ? "현재 명세나 요구사항이 달라졌습니다. 기준을 다시 조회한 뒤 새 가정으로 검토해 주세요." : report.reason}</AlertDescription></Alert>}
        <p className="impact-help">문맥 {report.coverage.included}/{report.coverage.total}개 사용 · {report.coverage.omitted}개 제외 · {report.coverage.truncated}개 일부 인용. 추정 결과는 확정된 영향이 아닙니다.</p>
        {report.inferred.length ? <ItemGroup>{report.inferred.map((item, index) => <Item key={index} variant="outline"><ItemContent>
          <ItemTitle>{item.topic}</ItemTitle><p>{item.effect}</p><ItemDescription>{item.rationale}</ItemDescription>
          <div className="impact-citations">{item.evidence.map((ref, i) => <ImpactCitation key={i} evidence={ref} report={report} inspect={inspect} />)}</div>
          {!item.evidence.length && <p className="impact-help">기존 명세의 직접 인용 없이 제안한 검토 주제입니다.</p>}
          <div className="impact-question"><strong>확인할 사항</strong><p>{item.question}</p><Button variant="secondary" size="sm" disabled={report.stale} onClick={() => addQuestion(item.question)}>수정 의견에 추가</Button></div>
        </ItemContent></Item>)}</ItemGroup> : report.status === "complete" && <Empty><EmptyHeader><EmptyTitle>추가 검토 제안이 없습니다</EmptyTitle><EmptyDescription>제공된 문맥에서 제안할 항목을 찾지 못했습니다. 영향이 없다는 보장은 아닙니다.</EmptyDescription></EmptyHeader></Empty>}
        {!!sources.length && <Trace><TraceCollapsible><TraceCollapsibleTrigger><TraceLine><TraceIcon><LinkIcon /></TraceIcon><TraceTitle>사용한 근거 {sources.length}개</TraceTitle></TraceLine></TraceCollapsibleTrigger><TraceCollapsibleContent>
          {sources.map(ref => <TraceLine key={ref.node_id}><TraceTitle><Button variant="link" size="sm" onClick={() => inspect(ref.node_id)}>{report.sources.find(source => source.node_id === ref.node_id)?.section || "근거 원문"}</Button></TraceTitle></TraceLine>)}
        </TraceCollapsibleContent></TraceCollapsible></Trace>}
        {!!report.limitations.length && <Alert><AlertTitle>분석 범위와 한계</AlertTitle><AlertDescription><ul>{report.limitations.map((text, index) => <li key={index}>{text}</li>)}</ul></AlertDescription></Alert>}
      </>}
    </section>
  </section>;
}
