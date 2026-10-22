import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { FolderPlusIcon, LinkSimpleIcon, CheckCircleIcon, CaretDownIcon } from "@phosphor-icons/react";
import { api, post } from "./api";
import { Button } from "./UI";
import { Field, FieldLabel, FieldDescription, FieldSet, FieldLegend } from "./components/ui/field";
import { NativeSelect } from "./components/ui/native-select";
import { InputGroup, InputGroupInput } from "./components/ui/input-group";
import { ItemGroup, Item, ItemContent, ItemTitle } from "./components/ui/item";
import { Badge } from "./components/ui/badge";
import { Dialog, DialogTrigger, DialogContent, DialogTitle, DialogDescription, DialogHeader, DialogFooter } from "./components/ui/dialog";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "./components/ui/collapsible";
import { Popover, PopoverTrigger, PopoverContent } from "./components/ui/popover";
import { Alert, AlertDescription } from "./components/ui/alert";
import { Empty, EmptyTitle } from "./components/ui/empty";
import { Skeleton } from "./components/ui/skeleton";
import { Pagination, PaginationContent, PaginationItem } from "./components/ui/pagination";
import "./project-decisions.css";

export type CommonDecision = { id: string; version: number; active: boolean; text: string; conditions: string; actor: "user" | "llm"; decision_id: string; job_id: string; project_id: string; completed_id: string; source_hash: string; source_available?: boolean; stale?: boolean; evidence: { item_id: string; section: string; quote: string }[] };
type Packet = { rows: CommonDecision[]; total: number; next_offset: number | null; project_id: string };
type Project = { id: string; name: string };
export type DecisionSelection = Pick<CommonDecision, "id" | "version" | "source_hash">;

function ErrorNotice({ error }: { error: string }) { return error ? <Alert role="alert"><AlertDescription>{error}</AlertDescription></Alert> : null; }
function DecisionSource({ item }: { item: CommonDecision }) {
  return <div className="pd-source"><Badge variant="outline">승인본 {item.completed_id.slice(0, 12)}</Badge><Popover><PopoverTrigger asChild><Button><LinkSimpleIcon size={16} aria-hidden />출처 확인</Button></PopoverTrigger><PopoverContent className="pd-citation"><strong>승인본 {item.completed_id.slice(0, 12)}</strong>{item.evidence.map((e, i) => <blockquote key={i}><small>{e.section} · {e.item_id}</small><p>{e.quote}</p></blockquote>)}{item.source_available === false ? <p>출처를 현재 조회할 수 없습니다. 당시 확인한 원문 사본입니다.</p> : <Link to={`/jobs/${encodeURIComponent(item.job_id)}?completed_id=${encodeURIComponent(item.completed_id)}`}>해당 승인 명세 열기</Link>}<Collapsible><CollapsibleTrigger>출처 전체 식별값</CollapsibleTrigger><CollapsibleContent><p>{item.completed_id}</p><p>SHA-256: {item.source_hash}</p></CollapsibleContent></Collapsible></PopoverContent></Popover></div>;
}
function DecisionBody({ item, descriptionId }: { item: CommonDecision; descriptionId?: string }) {
  return <><ItemTitle>{item.text}</ItemTitle><p id={descriptionId} className="pd-condition">적용 조건: {item.conditions || "기록된 추가 조건 없음"}</p><div className="pd-badges"><Badge variant="outline">{item.actor === "user" ? "사용자 작성" : "모델 작성"}</Badge><Badge variant="secondary">{item.active === false ? "등록 해제됨" : "등록 확인됨"}</Badge>{item.stale && <Badge variant="outline">등록 이후 새 승인본 있음</Badge>}{item.source_available === false && <Badge variant="outline">출처 확인 불가</Badge>}</div><DecisionSource item={item} /></>;
}

export function ProjectDecisionPicker({ projectId, onProject, selections, onSelections }: { projectId: string; onProject: (id: string) => void; selections: DecisionSelection[]; onSelections: (items: DecisionSelection[]) => void }) {
  const [projects, setProjects] = useState<Project[]>([]), [error, setError] = useState(""), [open, setOpen] = useState(false), [name, setName] = useState(""), [saving, setSaving] = useState(false);
  const sending = useRef(false), alive = useRef(true), creation = useRef(0);
  useEffect(() => { alive.current = true; return () => { alive.current = false; creation.current++; }; }, []);
  useEffect(() => { const controller = new AbortController(); void api<Project[]>("/api/projects", { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setProjects(value); }).catch(e => { if (!controller.signal.aborted) setError(`프로젝트 기능을 사용할 수 없습니다. ${e.message}`); }); return () => controller.abort(); }, []);
  async function create() {
    if (sending.current || !name.trim()) return;
    sending.current = true; setSaving(true); setError(""); const ticket = creation.current;
    try { const result = await post<Project>("/api/projects", { name: name.trim() }); if (!alive.current) return; setProjects(items => [...items, result]); if (ticket === creation.current) { onSelections([]); onProject(result.id); setOpen(false); setName(""); } }
    catch (e) { if (alive.current && ticket === creation.current) setError((e as Error).message); } finally { sending.current = false; if (alive.current) setSaving(false); }
  }
  return <section className="project-decisions" aria-label="프로젝트와 공통 결정"><Field><FieldLabel htmlFor="request-project">프로젝트</FieldLabel><div className="pd-controls"><NativeSelect id="request-project" value={projectId} onChange={e => { onSelections([]); onProject(e.target.value); }}><option value="">별도 프로젝트로 시작</option>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</NativeSelect><Dialog open={open} onOpenChange={value => { if (!value) creation.current++; setOpen(value); }}><DialogTrigger asChild><Button><FolderPlusIcon size={16} aria-hidden />프로젝트 만들기</Button></DialogTrigger><DialogContent className="pd-dialog"><DialogHeader><DialogTitle>개인 프로젝트 만들기</DialogTitle><DialogDescription>같은 프로젝트의 여러 대화에서 공통 결정을 선택해 재사용할 수 있습니다.</DialogDescription></DialogHeader><Field><FieldLabel htmlFor="project-name">프로젝트 이름</FieldLabel><InputGroup><InputGroupInput id="project-name" maxLength={120} value={name} onChange={e => setName(e.target.value)} /></InputGroup></Field><ErrorNotice error={error} /><DialogFooter><Button className="primary" disabled={saving || !name.trim()} onClick={() => void create()}>{saving ? "생성 중…" : "프로젝트 생성"}</Button></DialogFooter></DialogContent></Dialog></div><FieldDescription>등록된 결정도 직접 선택해야 이번 요청에 적용됩니다.</FieldDescription></Field><ErrorNotice error={error} />{projectId && <Collapsible key={projectId}><CollapsibleTrigger asChild><Button>공통 결정 선택 · {selections.length}개<CaretDownIcon aria-hidden size={15} /></Button></CollapsibleTrigger><CollapsibleContent><RegisteredDecisions projectId={projectId} selections={selections} onSelections={onSelections} /></CollapsibleContent></Collapsible>}</section>;
}

function RegisteredDecisions({ projectId, selections, onSelections }: { projectId: string; selections: DecisionSelection[]; onSelections: (items: DecisionSelection[]) => void }) {
  const [packet, setPacket] = useState<Packet | null>(null), [query, setQuery] = useState(""), [status, setStatus] = useState("active"), [offsets, setOffsets] = useState([0]), [retry, setRetry] = useState(0), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const sequence = useRef(0), sending = useRef(false), mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const offset = offsets.at(-1)!;
  useEffect(() => {
    const controller = new AbortController(), ticket = ++sequence.current;
    setPacket(null); setError("");
    const params = new URLSearchParams({ query, status, offset: String(offset) });
    void api<Packet>(`/api/projects/${encodeURIComponent(projectId)}/decisions?${params}`, { signal: controller.signal }).then(value => { if (!controller.signal.aborted && ticket === sequence.current) setPacket(value); }).catch(e => { if (!controller.signal.aborted && ticket === sequence.current) setError(e.message); });
    return () => controller.abort();
  }, [projectId, query, status, offset, retry]);
  async function deactivate(item: CommonDecision) {
    if (sending.current) return;
    sending.current = true; setBusy(true);
    try { await post(`/api/projects/${projectId}/decisions/${item.id}/deactivate`, { version: item.version }); if (mounted.current) { onSelections(selections.filter(s => s.id !== item.id)); setRetry(v => v + 1); } }
    catch (e) { if (mounted.current) setError((e as Error).message); }
    finally { sending.current = false; if (mounted.current) setBusy(false); }
  }
  return <FieldSet><FieldLegend>재사용할 공통 결정 · {selections.length}개 선택</FieldLegend><FieldDescription>원문과 적용 조건을 확인하세요. 새 승인본이 있어도 등록 원문은 자동으로 바뀌지 않습니다.</FieldDescription><div className="pd-controls"><InputGroup><InputGroupInput aria-label="공통 결정 검색" placeholder="결정 또는 적용 조건 검색" value={query} onChange={e => { setQuery(e.target.value); setOffsets([0]); }} /></InputGroup><NativeSelect aria-label="공통 결정 상태" value={status} onChange={e => { setStatus(e.target.value); setOffsets([0]); }}><option value="active">등록된 결정</option><option value="inactive">등록 해제됨</option><option value="all">전체 상태</option></NativeSelect></div><ErrorNotice error={error} />{!packet && !error && <Skeleton className="pd-skeleton" aria-label="공통 결정 조회 중" />}{packet && !packet.rows.length && <Empty><EmptyTitle>등록된 공통 결정이 없습니다</EmptyTitle><p>승인 명세에서 출처를 확인하고 등록할 수 있습니다.</p></Empty>}
    <ItemGroup>{packet?.rows.map(item => <Item key={item.id} variant="outline" className="pd-item"><label className="pd-check"><input type="checkbox" aria-label={item.text} aria-describedby={`condition-${item.id}`} checked={selections.some(s => s.id === item.id)} disabled={busy || !item.active || !item.source_available || (selections.length >= 20 && !selections.some(s => s.id === item.id))} onChange={e => { if (e.target.checked) onSelections([...selections, { id: item.id, version: item.version, source_hash: item.source_hash }]); else onSelections(selections.filter(s => s.id !== item.id)); }} /></label><ItemContent><DecisionBody item={item} descriptionId={`condition-${item.id}`} />{item.active && <Button disabled={busy} onClick={() => void deactivate(item)}>등록 해제</Button>}</ItemContent></Item>)}</ItemGroup><div className="pd-controls"><span>전체 {packet?.total ?? 0}개 · 최대 20개 선택</span><Button onClick={() => { onSelections([]); }}>선택 해제</Button><Button onClick={() => setRetry(v => v + 1)}>다시 조회</Button></div><DecisionPages offsets={offsets} setOffsets={setOffsets} next={packet?.next_offset ?? null} /></FieldSet>;
}

function DecisionPages({ offsets, setOffsets, next }: { offsets: number[]; setOffsets: (value: number[]) => void; next: number | null }) {
  return <Pagination aria-label="공통 결정 페이지"><PaginationContent><PaginationItem><Button disabled={offsets.length === 1} onClick={() => setOffsets(offsets.slice(0, -1))}>이전</Button></PaginationItem><PaginationItem>{offsets.length}페이지</PaginationItem><PaginationItem><Button disabled={next === null} onClick={() => next !== null && setOffsets([...offsets, next])}>다음</Button></PaginationItem></PaginationContent></Pagination>;
}

export function ApprovedDecisions({ jobId, completedId }: { jobId: string; completedId: string }) {
  const [open, setOpen] = useState(false), [packet, setPacket] = useState<Packet | null>(null), [offsets, setOffsets] = useState([0]), [chosen, setChosen] = useState<CommonDecision | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const opener = useRef<HTMLButtonElement | null>(null);
  const sequence = useRef(0), sending = useRef(false), registration = useRef(0), alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; registration.current++; }; }, []);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController(), ticket = ++sequence.current;
    setPacket(null); setError("");
    void api<Packet>(`/api/jobs/${jobId}/decision-candidates?completed_id=${completedId}&offset=${offsets.at(-1)}`, { signal: controller.signal }).then(value => { if (!controller.signal.aborted && ticket === sequence.current) setPacket(value); }).catch(e => { if (!controller.signal.aborted && ticket === sequence.current) setError(e.message); });
    return () => { controller.abort(); sequence.current++; };
  }, [jobId, completedId, open, offsets]);
  async function register() {
    if (!chosen || sending.current) return;
    sending.current = true; setBusy(true); setError(""); const ticket = registration.current;
    try { await post(`/api/projects/${chosen.project_id}/decisions`, { job_id: jobId, completed_id: completedId, decision_id: chosen.decision_id, source_hash: chosen.source_hash }); if (alive.current && ticket === registration.current) { setChosen(null); setNotice("프로젝트 공통 결정으로 등록했습니다. 다음 요청에서 직접 선택해 적용하세요."); } }
    catch (e) { if (alive.current && ticket === registration.current) setError((e as Error).message); }
    finally { sending.current = false; if (alive.current) setBusy(false); }
  }
  return <section className="project-decisions"><Collapsible open={open} onOpenChange={setOpen}><CollapsibleTrigger asChild><Button><CheckCircleIcon size={17} aria-hidden />승인본의 공통 결정 등록<CaretDownIcon size={15} aria-hidden /></Button></CollapsibleTrigger><CollapsibleContent><p>명세에 연결된 구조화 결정만 등록할 수 있습니다. 등록해도 다음 요청에 자동 적용되지 않습니다.</p><ErrorNotice error={error} /><p role="status">{notice}</p>{!packet && !error && <Skeleton className="pd-skeleton" />}{packet && !packet.rows.length && <Empty><EmptyTitle>등록할 수 있는 구조화 결정이 없습니다</EmptyTitle><p>출처와 명세 연결이 확인되는 결정만 제공합니다. 과거 본문에서 임의로 추출하지 않습니다.</p></Empty>}<ItemGroup>{packet?.rows.map((item, i) => <Item className="pd-item" variant="outline" key={item.decision_id}><ItemContent><ItemTitle>{item.text}</ItemTitle><p>적용 조건: {item.conditions || "기록된 추가 조건 없음"}</p><Badge variant="outline">{item.actor === "user" ? "사용자 작성" : "모델 작성"}</Badge><DecisionSource item={item} /><Button onClick={event => { opener.current = event.currentTarget; registration.current++; setChosen({ ...item, id: `candidate-${i}` }); setError(""); }}>공통 결정으로 등록</Button></ItemContent></Item>)}</ItemGroup><DecisionPages offsets={offsets} setOffsets={setOffsets} next={packet?.next_offset ?? null} /></CollapsibleContent></Collapsible><Dialog open={!!chosen} onOpenChange={value => { if (!value) { registration.current++; setChosen(null); } }}><DialogContent className="pd-dialog" onCloseAutoFocus={event => { event.preventDefault(); if (opener.current?.isConnected) opener.current.focus(); }}><DialogHeader><DialogTitle>공통 결정 등록 확인</DialogTitle><DialogDescription>아래 원문과 적용 조건의 재사용을 확인합니다. 작성 주체는 유지됩니다.</DialogDescription></DialogHeader>{chosen && <><p>{chosen.text}</p><p>적용 조건: {chosen.conditions || "기록된 추가 조건 없음"}</p><Badge variant="outline">{chosen.actor === "user" ? "사용자 작성" : "모델 작성"}</Badge><DecisionSource item={chosen} /></>}<ErrorNotice error={error} /><DialogFooter><Button className="primary" disabled={busy} onClick={() => void register()}>{busy ? "등록 중…" : "이 원문과 조건을 등록"}</Button></DialogFooter></DialogContent></Dialog></section>;
}

export function ReusedDecisions({ jobId, count }: { jobId: string; count: number }) {
  const [open, setOpen] = useState(false), [packet, setPacket] = useState<Packet | null>(null), [error, setError] = useState(""), [offsets, setOffsets] = useState([0]);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController(); setPacket(null); setError("");
    void api<Packet>(`/api/jobs/${jobId}/reused-decisions?offset=${offsets.at(-1)}`, { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setPacket(value); }).catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [jobId, open, offsets]);
  if (!count) return null;
  return <section className="project-decisions"><Collapsible open={open} onOpenChange={setOpen}><CollapsibleTrigger asChild><Button>이번 요청에 재사용한 결정 {count}개<CaretDownIcon aria-hidden size={16} /></Button></CollapsibleTrigger><CollapsibleContent><p>요청 접수 당시 확인한 사본입니다. 등록 해제나 새 승인본이 이 내용을 바꾸지 않습니다.</p><ErrorNotice error={error} />{!packet && !error && <Skeleton className="pd-skeleton" />}<ItemGroup>{packet?.rows.map(item => <Item className="pd-item" key={item.id}><ItemContent><DecisionBody item={item} /></ItemContent></Item>)}</ItemGroup><DecisionPages offsets={offsets} setOffsets={setOffsets} next={packet?.next_offset ?? null} /></CollapsibleContent></Collapsible></section>;
}
