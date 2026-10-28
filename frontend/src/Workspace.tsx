import { ChatCircleDotsIcon, ClockCounterClockwiseIcon, FileTextIcon, GraphIcon, PlusIcon, SparkleIcon, SquaresFourIcon } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { post } from "./api";
import { useAuth } from "./Auth";
import { ChangeReview } from "./ChangeReview";
import { AppSidebar } from "./components/AppSidebar";
import { PromptInput } from "./components/PromptInput";
import { Badge } from "./components/ui/badge";
import { Input } from "./components/ui/input";
import { SidebarGroup, SidebarGroupLabel, SidebarInset, SidebarMenu, SidebarMenuButton, SidebarMenuItem, SidebarProvider, SidebarTrigger } from "./components/ui/sidebar";
import { Tabs, TabsList, TabsTrigger } from "./components/ui/tabs";
import { Conversation } from "./Conversation";
import { DocumentView } from "./DocumentView";
import { ExecutionTimeline, ResearchResult } from "./ExecutionTimeline";
import { ImplementationPackage } from "./ImplementationPackage";
import Knowledge from "./Knowledge";
import { ProjectDecisionPicker, ReusedDecisions, type DecisionSelection } from "./ProjectDecisions";
import { questionDetails } from "./QuestionActions";
import { ServiceStatusNotice, serviceState } from "./ServiceStatus";
import type { Job, RecordData, Step } from "./types";
import { Button, Notice, formatTime, statusLabel, usageLabel } from "./UI";
import { useJobSession } from "./useJobSession";
export function graphNodes(job: Job): Step[] {
  return job.execution_graph?.nodes || [];
}
const stageLabel = (node?: Step) =>
  node?.title ||
  {
    request: "요청 접수",
    planner: "작업 계획",
    project_context: "프로젝트 자료 확인",
    knowledge_search: "기존 근거 확인",
    web_research: "외부 자료 조사",
    ask_user: "사용자 결정 확인",
    blocked: "진행 중단",
    requirement_lock_stage: "요구사항 확정",
    generate: "요청 접수",
    interview: "요청 분석",
    await_user: "요구사항 확인 필요",
    answer: "답변 저장",
    requirement_lock: "요구사항 확정",
    revise: "수정 의견",
    spec_compile: "명세 생성",
    checklist_critic: "명세 검토",
    review_resolution: "해결 방법 판단",
    approve: "최종 승인",
    compose_candidate: "검토본 준비",
    critical_report: "명세 진행 중단 보고",
  }[node?.stage || ""] ||
  "실행 단계";
export default function Workspace() {
  const auth = useAuth(),
    navigate = useNavigate(),
    location = useLocation(),
    { id } = useParams();
  const session = useJobSession();
  const { jobs, job, step, tab, setTab, detail, busy, loading, connection, refresh } = session;
  const [surface, setSurface] = useState("workspace"), [query, setQuery] = useState(""), [filter, setFilter] = useState("");
  const navigation = useRef(location.key), selectedId = useRef(id);
  const [projectId, setProjectId] = useState("");
  const [decisionSelections, setDecisionSelections] = useState<DecisionSelection[]>([]);
  useEffect(() => { setProjectId(""); setDecisionSelections([]); }, [auth.user?.id]);
  const draftKey = `draft:${auth.user?.id || "local"}`;
  const [request, setRequest] = useState(
    () => sessionStorage.getItem(draftKey) || "",
  );
  selectedId.current = id;
  navigation.current = location.key;
  const isAdmin = !auth.publicMode || auth.user?.role === "admin",
    blocked = busy || serviceState(auth.publicMode, auth.status).blocked;
  useEffect(() => { setSurface("workspace"); }, [id]);
  const node = job && [...graphNodes(job), ...(job.completed_documents || [])].find((item: Step) => item.id === step);
  useEffect(() => {
    const leave = (event: BeforeUnloadEvent) => {
      if (
        request.trim() ||
        (document.activeElement instanceof HTMLTextAreaElement &&
          document.activeElement.value)
      ) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", leave);
    return () => window.removeEventListener("beforeunload", leave);
  }, [request]);
  const [evidenceOnly, setEvidenceOnly] = useState(false);
  useEffect(() => { setEvidenceOnly(false); }, [id]);
  function selectStep(value: string, requirements = false) {
    setEvidenceOnly(requirements);
    session.select(value);
    setTab("document");
  }
  async function mutate(action: string, payload: unknown) {
    const target = id;
    try {
      if (await session.command(action, action === "retry" ? null : payload, action === "retry" && payload ? payload as RecordData : {}) && selectedId.current === target) auth.setNotice(action === "stop" ? "이 작업의 중지를 요청했습니다." : "작업을 대기열에 넣었습니다.");
    } catch (e) {
      if (action !== "message") auth.setNotice((e as Error).message);
      throw e;
    }
  }
  async function generate() {
    if (!request.trim()) { auth.setNotice("개발 요청을 입력하세요."); return; }
    const submitted = navigation.current;
    try {
      const value = await session.command("generate", request.trim(), { project_id: projectId || null, decision_reuse: decisionSelections });
      if (!value) return;
      if (submitted === navigation.current) {
        setRequest(""); setDecisionSelections([]); sessionStorage.removeItem(draftKey);
        navigate(`/jobs/${value.id}`);
      }
      auth.setNotice("새 작업을 대기열에 넣었습니다.");
    } catch (e) { auth.setNotice((e as Error).message); }
  }
  const filtered = jobs.filter(
    (j) =>
      (!query ||
        `${j.request} ${j.id}`.toLowerCase().includes(query.toLowerCase())) &&
      (!filter ||
        (filter === "active"
          ? [
              "queued",
              "running",
              "NEEDS_USER_INPUT",
              "PASS_PENDING_USER_APPROVAL",
            ].includes(j.status)
          : j.status === filter)),
  );
  const actualJob = job?.id === id ? job : null;
  const result = detail?.result || {};
  const currentDocument = actualJob && [...graphNodes(actualJob)].reverse().find((node) => node.has_document && (!actualJob.execution_id || !node.execution_id || node.execution_id === actualJob.execution_id));
  const showConversation = () => setTab("conversation");
  const selectedDetail = () => actualJob ? <>
    {tab === "history" && detail && !detail.unavailable && <StepResult node={node} detail={detail} />}
    {detail?.unavailable ? (
      <Notice>기록 확인 불가: {detail.message}</Notice>
    ) : !detail ? (
      <p role="status">
        {loading ? "작업" : "단계 상세"}를 불러오는
        중입니다.
      </p>
    ) : detail.document?.content && tab === "history" ? (
      <Button onClick={() => setTab("document")}>이 단계의 명세 문서 보기</Button>
    ) : detail.document?.content ? (
      <DocumentView
        jobId={actualJob.id}
        stepId={step}
        initialLanguage={new URLSearchParams(location.search).has("completed_id") ? "en" : "ko"}
        document={detail.document}
        reviewOnly={evidenceOnly}
        onShowDocument={() => setEvidenceOnly(false)}
        onQuestion={question => {
          const key = `draft:${auth.user?.id || "local"}:${actualJob.id}:feedback`;
          const prior = sessionStorage.getItem(key)?.trim();
          sessionStorage.setItem(key, prior ? `${prior}\n\n${question}` : question);
          showConversation();
        }}
      />
    ) : tab !== "history" ? (
      <StepResult node={node} detail={detail} hideQuestions={!!actualJob.session_events?.find(event => event.id === node?.execution_id)?.questions?.length && JSON.stringify(actualJob.session_events?.find(event => event.id === node?.execution_id)?.questions) === JSON.stringify(detail?.result?.questions || detail?.result?.blocking_questions || [])} />
    ) : null}
    {(result.issues?.length ||
      result.resolved_issues?.length ||
      result.report) && <Issues result={result} open={tab === "history"} />}

  </> : null;
  return (
    <SidebarProvider className="shell">
      <AppSidebar>
        <Button
          className="primary new-job"
          onClick={() => {
            navigate("/");
            setSurface("workspace");
          }}
        >
          <PlusIcon size={18} aria-hidden />새 작업
        </Button>
        <SidebarGroup className="main-group"><SidebarGroupLabel>작업 공간</SidebarGroupLabel><nav className="primary-nav"><SidebarMenu>
          <SidebarMenuItem><SidebarMenuButton asChild isActive={surface === "workspace"}><Button
            aria-current={surface === "workspace" ? "page" : undefined}
            onClick={() => setSurface("workspace")}
          >
            <SquaresFourIcon weight="duotone" size={20} aria-hidden />작업 공간
          </Button></SidebarMenuButton></SidebarMenuItem>
          <SidebarMenuItem><SidebarMenuButton asChild isActive={surface === "knowledge"}><Button
            disabled={false}
            aria-current={surface === "knowledge" ? "page" : undefined}
            onClick={() => setSurface("knowledge")}
          >
            <GraphIcon weight="duotone" size={20} aria-hidden />지식 검색
          </Button></SidebarMenuButton></SidebarMenuItem>
        </SidebarMenu></nav></SidebarGroup>
        <SidebarGroup className="history">
          <label className="sr-only" htmlFor="history-query">
            작업 검색
          </label>
          <Input
            id="history-query"
            placeholder="작업 검색"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <select
            aria-label="작업 상태"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="">전체 상태</option>
            <option value="active">진행 중</option>
            <option value="NEEDS_USER_INPUT">요구사항 확인 필요</option>
            <option value="FINALIZED">최종 완료</option>
            <option value="error">오류</option>
            <option value="CRITICAL_BLOCKED">명세 진행 중단</option>
          </select>
          <SidebarGroupLabel asChild><h2>
            대화 세션 <span>{filtered.length}</span>
          </h2></SidebarGroupLabel>
          <nav aria-label="작업 기록"><SidebarMenu>
            {!filtered.length && (query || filter) && <li className="history-empty" role="status">조건에 맞는 작업이 없습니다.</li>}
            {filtered.map((item) => (
              <SidebarMenuItem key={item.id}><SidebarMenuButton asChild isActive={id === item.id} className="session-menu-link"><Link
                to={`/jobs/${item.id}`}
                aria-current={id === item.id ? "page" : undefined}
                onClick={() => {
                  setSurface("workspace");
                }}
              >
                <strong>{item.request?.slice(0, 70) || "저장된 작업"}</strong>
                <small>
                  {statusLabel(item.status)} ·{" "}
                  {formatTime(item.updated_at || item.created_at)}
                </small>
              </Link></SidebarMenuButton></SidebarMenuItem>
            ))}
          </SidebarMenu></nav>
        </SidebarGroup>
      </AppSidebar>
      <SidebarInset className="workspace-content">
        <div className="workspace-topbar">
          <div className="mobile-workspace-bar"><SidebarTrigger  /><span>MAGI 작업 공간</span></div>
          <Account />
        </div>
        <main>
          <header className={`workspace-header ${id && surface === "workspace" ? "chat-header" : ""}`}>
            <div><span className="eyebrow">MAGI / {surface === "knowledge" ? "KNOWLEDGE" : "WORKSPACE"}</span>
              <h1>{surface === "knowledge" ? "지식 검색" : id ? actualJob?.request?.slice(0, 70) || "작업 불러오는 중…" : "새 명세 만들기"}</h1>
            </div>
            {actualJob && surface === "workspace" && <div className="chat-header-actions"><Badge variant="secondary">{statusLabel(actualJob.status)}</Badge>{currentDocument && <Button onClick={() => selectStep(currentDocument.id)}><FileTextIcon size={17} aria-hidden />명세 열기</Button>}</div>}
          </header>
          <Notice>{auth.notice || connection}</Notice>
          {surface === "knowledge" ? (
            <Knowledge selectedJobId={id} />
          ) : (
            <>
              {!id ? (
                <section className="chat-welcome">
                  <div className="welcome-mark"><SparkleIcon weight="duotone" size={28} aria-hidden /></div>
                  <h2>무엇을 만들고 싶으신가요?</h2>
                  <p>완벽하게 정리하지 않아도 괜찮습니다.<br />요청을 바탕으로 필요한 내용을 함께 구체화합니다.</p>
                  <ProjectDecisionPicker key={auth.user?.id || "local"} projectId={projectId} onProject={setProjectId} selections={decisionSelections} onSelections={setDecisionSelections} />
                  <label htmlFor="request-text">개발 요청</label>
                  <PromptInput id="request-text" label="개발 요청" buttonLabel={decisionSelections.length ? `선택한 결정 ${decisionSelections.length}개와 함께 생성` : "명세 생성 시작"} rows={5} value={request} disabled={blocked}
                    placeholder="예: 팀이 매주 진행 상황을 공유할 수 있는 보고서 생성 기능을 만들어주세요."
                    onChange={(event) => { setRequest(event.target.value); sessionStorage.setItem(draftKey, event.target.value); }} onSend={() => void generate()} />
                  <div className="request-guidance"><span>만들고 싶은 것</span><span>사용할 사람</span><span>지켜야 할 조건</span></div>
                  <p className="subtle">요청과 답변은 명세 생성을 위해 OpenAI에 전송됩니다.</p>
                </section>
              ) : actualJob ? (
                <>
                  <ReusedDecisions key={actualJob.id} jobId={actualJob.id} count={actualJob.reused_decision_count || 0} />
                  <Tabs value={tab} onValueChange={setTab}><TabsList className="workspace-tabs" aria-label="작업 보기">
                    {[
                      ["conversation", "대화"],
                      ["document", "명세"],
                      ...(isAdmin ? [["history", "실행 이력"]] : []),
                    ].map(([key, label]) => (
                      <TabsTrigger key={key} value={key} id={`workspace-tab-${key}`} aria-controls={`workspace-panel-${key}`} className="button">
                        {key === "document" ? <FileTextIcon size={18} aria-hidden /> : key === "conversation" ? <ChatCircleDotsIcon size={18} aria-hidden /> : <ClockCounterClockwiseIcon size={18} aria-hidden />}{label}
                      </TabsTrigger>
                    ))}
                  </TabsList></Tabs>
                  {tab !== "conversation" && <CompletedDocuments job={actualJob} select={selectStep} />}
                  <div role="tabpanel" id={`workspace-panel-${tab}`} aria-labelledby={`workspace-tab-${tab}`} tabIndex={0}>
                  {tab === "conversation" ? (
                    <>
                    {["queued", "running"].includes(actualJob.status) && <Button disabled={busy} onClick={() => void mutate("stop", undefined).catch(() => {})}>이 작업 중지</Button>}
                  <Conversation key={actualJob.id} job={actualJob} select={selectStep} onAction={mutate} busy={busy} />
                    </>
                  ) : (
                    <div className="document-action-layout">
                      <section className="document-panel">
                        {detail?.change_review && <details className="document-change-review"><summary>명세 변경 검토 · {detail.change_review.changes?.length || 0}건</summary><ChangeReview review={detail.change_review} /></details>}
                        {tab === "history" && actualJob.usage && <p className="subtle">{usageLabel(actualJob.usage)}</p>}
                        {tab === "history" && (
                          <>
                            <ExecutionTimeline key={actualJob.id} job={actualJob} nodes={graphNodes(actualJob)} selected={step} select={session.select} detail={selectedDetail()} />
                            {actualJob.execution_graph?.recording_incomplete && <Notice>일부 이력 기록 누락</Notice>}
                          </>
                        )}
                        {tab !== "history" && selectedDetail()}
                      </section>
                      <aside className="action-panel">
                        <section className="action-card document-chat-cta"><p>답변·수정·승인은 대화에서 진행합니다.</p><Button className="primary" onClick={showConversation}><ChatCircleDotsIcon size={18} aria-hidden />대화에서 답변하기</Button></section>
                      </aside>
                    </div>
                  )}
                  </div>

                </>
              ) : (
                <p role="status">
                  {loading
                    ? "작업을 불러오는 중입니다."
                    : "작업을 표시할 수 없습니다."}
                </p>
              )}
            </>
          )}
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}

function Account() {
  return <header className="account-header"><SidebarTrigger className="desktop-sidebar-trigger" /><ServiceStatusNotice /></header>;
}
function CompletedDocuments({
  job,
  select,
}: {
  job: Job;
  select: (id: string) => void;
}) {
  const [selected, setSelected] = useState("");
  return (
    <details className="completed-documents"><summary>완료 명세·다운로드</summary><div className="completed-document-controls">
      {(job.latest_completed || job.status === "FINALIZED") && <ImplementationPackage key={`${job.id}:${job.latest_completed?.id || "latest"}`} jobId={job.id} completedId={job.latest_completed?.id} label="최근 승인본 구현 묶음" />}
      <span>
        {job.status === "FINALIZED"
          ? "최근 완료본"
          : job.latest_completed
            ? "현재 작업 중인 초안 · 이전 완료본은 별도 보존됩니다."
            : "아직 승인된 완료 명세가 없습니다."}
      </span>
      {job.latest_completed?.step_id && (
        <Button onClick={() => select(job.latest_completed.step_id)}>
          {job.status === "FINALIZED"
            ? "최근 완료 명세 열기"
            : "이전 완료본 열기"}
        </Button>
      )}
      {job.completed_documents?.length > 1 && (
        <>
          <select
            aria-label="보존된 완료 명세"
            value={selected || job.completed_documents[0].id}
            onChange={(e) => setSelected(e.target.value)}
          >
            {job.completed_documents.map((d: RecordData, i: number) => (
              <option key={d.id} value={d.id}>
                완료본 {i + 1}
              </option>
            ))}
          </select>
          <Button
            onClick={() => select(selected || job.completed_documents[0].id)}
          >
            선택한 완료본 열기
          </Button>
        </>
      )}
    </div></details>
  );
}
export function StepResult({ node, detail, hideQuestions = false }: { node?: Step; detail: RecordData; hideQuestions?: boolean }) {
  const result = detail.result || {};
  const source = result.requirements || result;
  const groups = Array.isArray(source)
    ? [["확정 요구사항", source]]
    : [
        ["필수 요구사항", source.mandatory_requirements],
        ["권장 요구사항", source.recommended_requirements],
        ["선택 요구사항", source.optional_requirements],
        ["제약 조건", source.constraints],
      ];
  return (
    <section className="step-result">
      <span className="eyebrow">{statusLabel(node?.status)}</span>
      <h2>{stageLabel(node)}</h2>
      {node?.stage === "planner" && (result.plan ? <section aria-label="저장된 작업 계획">
        <h3>{result.plan.goal}</h3>
        <p><strong>선택한 작업: </strong>{stageLabel({ id: "", stage: result.plan.action })}</p>
        <p><strong>판단 근거: </strong>{result.plan.reason}</p>
        {result.plan.target && <p><strong>작업 대상: </strong>{result.plan.target}</p>}
        {result.plan.expected_result && <p><strong>예상 결과: </strong>{result.plan.expected_result}</p>}
        {!!result.plan.tasks?.length && <ul>{result.plan.tasks.map((task: RecordData) => <li key={task.id}>{task.title} · {({ pending: "예정", completed: "완료", blocked: "대기" } as Record<string, string>)[task.status] || task.status}</li>)}</ul>}
        {!!result.plan.input_refs?.length && <p><strong>참조한 근거: </strong>{result.plan.input_refs.join(", ")}</p>}
        {!!result.plan.affected_requirement_ids?.length && <p><strong>관련 요구사항: </strong>{result.plan.affected_requirement_ids.join(", ")}</p>}
      </section> : <p>당시 작업 계획의 상세 내용이 저장되지 않았습니다.</p>)}
      {node?.stage === "review_resolution" && result.action && <p><strong>다음 처리: </strong>{({ repair: "초안 수정·재검토", ask_user: "사용자 결정 확인", stop: "보완 중단", approve: "승인 후보 준비" } as Record<string, string>)[result.action] || result.action}</p>}
      {result.wait_reason && <p><strong>중단·대기 사유: </strong>{result.wait_reason}</p>}
      {result.diagnostic && <section aria-label="실패 진단"><h3>실패 진단</h3>
        <p>{result.diagnostic.error_code || "분류되지 않은 실행 오류"}</p>
        {result.diagnostic.error_stage && <p>실패 단계: {result.diagnostic.error_stage}</p>}
        {!!result.diagnostic.failed_checks?.length && <p>검증 항목: {result.diagnostic.failed_checks.join(", ")}</p>}
      </section>}
      {detail.recording_incomplete && (
        <Notice>
          일부 상세 기록이 누락되었습니다. 표시 가능한 결과만 제공합니다.
        </Notice>
      )}
      {node?.stage !== "web_research" && <p>{["단계를 완료했습니다.", "사용자 작업을 접수했습니다."].includes(result.summary || node?.summary) ? "상세 결과 기록 없음" : result.summary || node?.summary || "상세 결과 기록 없음"}</p>}
      {node?.stage === "web_research" && <ResearchResult research={detail.research || result.research} />}
      {result.purpose && <p>{result.purpose}</p>}
      {result.request && <p>{result.request}</p>}
      {result.feedback && <p>{result.feedback}</p>}
      {(result.answers || []).map((answer: RecordData, i: number) => (
        <section className="execution-answer" key={i}><h3>질문</h3><p>{answer.question ? questionDetails(answer.question, i).label : "질문 원문 기록 없음"}</p><h3>답변</h3><p>{answer.answer || "답변 기록 없음"}</p>{answer.question_id && <details><summary>질문 참조</summary><code>{answer.question_id}</code></details>}</section>
      ))}
      {!hideQuestions && (result.questions || result.blocking_questions || []).map((q: string, i: number) => <p key={i}>{questionDetails(q, i).label}</p>)}
      {groups.map(([label, items]) =>
        Array.isArray(items) && items.length ? (
          <section key={String(label)}>
            <h3>{String(label)}</h3>
            <ul>
              {items.map((item: RecordData | string, i: number) => (
                <li key={i}>
                  {typeof item === "string"
                    ? item
                    : `${item.id || ""} ${item.text || ""}`}
                </li>
              ))}
            </ul>
          </section>
        ) : null,
      )}

    </section>
  );
}
function Issues({ result, open = false }: { result: RecordData; open?: boolean }) {
  const render = (items: RecordData[], resolved = false) =>
    items.map((issue, i) => (
      <article className="issue-card" key={i}>
        <small>
          {resolved
            ? "해소됨"
            : issue.lifecycle === "persistent"
              ? "계속 남음"
              : "새 지적"}{" "}
          · {issue.severity}
        </small>
        <h4>{issue.problem || issue.title || "검토 항목"}</h4>
        {[
          ["requirement_id", "요구사항"],
          ["section", "섹션"],
          ["defect_kind", "결함 유형"],
          ["resolution_reason", "해결 판단"],
          ["resolution_kind", "처리 분류"],
          ["decision_answer_id", "재사용한 답변"],
          ["missing_information", "미확정 내용"],
          ["decision_key", "결정 주제"],
          ["required_change", "필요한 수정"],
        ].map(([key, label]) =>
          issue[key] ? (
            <p key={key}>
              <strong>{label}: </strong>
              {issue[key]}
            </p>
          ) : null,
        )}
        {!!issue.basis_refs?.length && <p><strong>확정 근거: </strong>{issue.basis_refs.join(", ")}</p>}
        {(Array.isArray(issue.evidence)
          ? issue.evidence
          : issue.evidence
            ? [issue.evidence]
            : []
        ).map((e: RecordData | string, n: number) => (
          <blockquote key={n}>
            {typeof e === "string" ? e : `${e.source || ""} · ${e.quote || ""}`}
          </blockquote>
        ))}
      </article>
    ));
  return (
    <details className="issues" open={open || undefined}>
      <summary>검토 항목 · {result.issues?.length || 0}건</summary>
      {render(result.issues || [])}
      {!!result.resolved_issues?.length && (
        <details>
          <summary>
            다음 검토에서 해소됨 · {result.resolved_issues.length}건
          </summary>
          {render(result.resolved_issues, true)}
        </details>
      )}
      {result.report && (
        <details>
          <summary>원본 검토 보고서 보기</summary>
          <pre>{result.report}</pre>
        </details>
      )}
    </details>
  );
}
