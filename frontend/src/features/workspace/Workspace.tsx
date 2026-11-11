import { Stack } from "@astryxdesign/core/Stack";
import { Selector } from "@astryxdesign/core/Selector";
import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { StepResult } from "../execution/StepResult";
import { StopDiagnostic } from "../execution/StopDiagnostic";
import { FailureDiagnostic } from "../execution/FailureDiagnostic";
import { Issues } from "../execution/Issues";
export { StepResult } from "../execution/StepResult";
export { StopDiagnostic } from "../execution/StopDiagnostic";
import { ChatCircleDotsIcon, ClockCounterClockwiseIcon, FileTextIcon, GraphIcon, PlusIcon, SquaresFourIcon } from "@phosphor-icons/react";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { post } from "../../shared/api/api";
import { useAuth } from "../auth/Auth";
import { ChangeReview } from "../requirements/ChangeReview";
import { AppSidebar } from "./AppSidebar";
import { PromptInput } from "../../shared/ui/PromptInput";
import { StatusIcon } from "../../shared/ui/StatusIcon";
import { SessionLink } from "./SessionLink";
import { Input } from "../../shared/ui/input";
import { SidebarGroup, SidebarGroupLabel, SidebarInset, SidebarMenu, SidebarMenuButton, SidebarMenuItem, SidebarProvider, SidebarTrigger } from "../../shared/ui/sidebar";
import { Tabs, TabsList, TabsTrigger } from "../../shared/ui/tabs";
import { Conversation } from "../conversation/Conversation";
import { DocumentView } from "../documents/DocumentView";
import { ExecutionTimeline, ResearchResult } from "../execution/ExecutionTimeline";
import { ImplementationPackage } from "../documents/ImplementationPackage";
import Knowledge from "../knowledge/Knowledge";
import { ProjectDecisionPicker, ReusedDecisions, type DecisionSelection } from "../projects/ProjectDecisions";
import { questionDetails } from "../conversation/QuestionActions";
import { ServiceStatusNotice, serviceState } from "./ServiceStatus";
import type { Job, Step } from "../../shared/types";
import { Button, Notice, UsageSummary } from "../../shared/ui/UI";
import { useJobSession } from "./useJobSession";
import { workspaceStage, workspaceStageMessage, type WorkspaceStage } from "./progress-state";
import { currentDocumentStep } from "../execution/step-selection";
export function graphNodes(job: Job): Step[] {
  return job.execution_graph?.nodes || [];
}
export default function Workspace() {
  const auth = useAuth(),
    navigate = useNavigate(),
    location = useLocation(),
    { id } = useParams();
  const session = useJobSession();
  const { jobs, job, step, tab, setTab, detail, busy, loading, connection, refresh } = session;
  const [surface, setSurface] = useState("workspace"), [query, setQuery] = useState(""), [filter, setFilter] = useState("");
  const [reviewPanelOpen, setReviewPanelOpen] = useState(false);
  const reviewToggle = useRef<HTMLButtonElement>(null);
  const reviewClose = useRef<HTMLButtonElement>(null);
  const appendQuestion = useRef<((text: string) => boolean) | null>(null);
  const focusAddedQuestion = useRef(false);
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
  useEffect(() => {
    if (!reviewPanelOpen || window.innerWidth >= 1920) return;
    if (focusAddedQuestion.current && id) {
      const input = document.getElementById(`agent-message-${id}`) || document.getElementById(`feedback-${id}`);
      if (input) input.focus(); else reviewClose.current?.focus();
    } else reviewClose.current?.focus();
    focusAddedQuestion.current = false;
  }, [reviewPanelOpen, id]);
  const node = job ? [...graphNodes(job), ...(job.completed_documents || [])].find((item: Step) => item.id === step) : undefined;
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
      if (await session.command(action, ["retry", "approve"].includes(action) ? null : payload, action === "approve" ? { accept_remaining_issues: typeof payload === "object" && payload !== null && "accept_remaining_issues" in payload && payload.accept_remaining_issues === true } : action === "retry" && payload ? { replay_pending: typeof payload === "object" && payload !== null && "replay_pending" in payload && payload.replay_pending === true } : {}) && selectedId.current === target) auth.setNotice(action === "stop" ? "이 작업의 중지를 요청했습니다." : "작업을 대기열에 넣었습니다.");
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
  const currentDocument = actualJob ? currentDocumentStep(actualJob) : undefined;
  const historicalDocument = tab === "document" && !!step && step !== currentDocument;
  const retryStatus = actualJob && ["error", "interrupted"].includes(actualJob.status) && actualJob.execution_id && node?.execution_id === actualJob.execution_id ? actualJob : undefined;
  const result = detail?.result || {};
  const mainRef = useRef<HTMLElement>(null);
  useEffect(() => {
    // 실시간 갱신에는 반응하지 않고 화면 전환에만 위치를 초기화한다.
    mainRef.current?.scrollTo?.({ top: 0, behavior: "instant" });
    window.scrollTo?.({ top: 0, behavior: "instant" });
  }, [id, surface, tab]);
  const workspaceTabs = actualJob && surface === "workspace" ? <Tabs value={tab} onValueChange={setTab}><TabsList className="workspace-tabs" aria-label="작업 보기">
    {[["conversation", "대화"], ["document", "명세"], ...(isAdmin ? [["history", "실행 이력"]] : [])].map(([key, label]) =>
      <TabsTrigger key={key} value={key} id={`workspace-tab-${key}`} aria-controls={`workspace-panel-${key}`} className="button">
        {key === "document" ? <FileTextIcon size={16} aria-hidden /> : key === "conversation" ? <ChatCircleDotsIcon size={16} aria-hidden /> : <ClockCounterClockwiseIcon size={16} aria-hidden />}{label}
      </TabsTrigger>)}
  </TabsList></Tabs> : null;
  const selectedDetail = () => actualJob ? <>
    {tab !== "history" && detail?.document?.content && <StopDiagnostic value={result.stop_diagnostic} />}
    {tab !== "history" && detail?.document?.content && ["failed", "error"].includes(node?.status || "") && <FailureDiagnostic value={result.diagnostic} fallbackStage={node?.stage} retry={retryStatus} />}
    {tab === "history" && detail && !detail.unavailable && <StepResult node={node} detail={detail} retry={retryStatus} />}
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
        document={detail.document}
        reviewOnly={evidenceOnly}
        onShowDocument={() => setEvidenceOnly(false)}
        onQuestion={question => {
          if (historicalDocument) { auth.setNotice("현재 검토본에서 수정 의견을 작성해주세요."); return; }
          if (appendQuestion.current?.(question)) { focusAddedQuestion.current = true; setReviewPanelOpen(true); }
          else auth.setNotice("현재 작업에서 수정 의견을 추가할 수 없습니다.");
        }}
      />
    ) : tab !== "history" ? (
      <StepResult node={node} detail={detail} retry={retryStatus} hideQuestions={!!actualJob.session_events?.find(event => event.id === node?.execution_id)?.questions?.length && JSON.stringify(actualJob.session_events?.find(event => event.id === node?.execution_id)?.questions) === JSON.stringify(detail?.result?.questions || detail?.result?.blocking_questions || [])} />
    ) : null}
    {(result.issues?.length ||
      result.resolved_issues?.length ||
      result.report) && <Issues result={result} open={tab === "history"} />}

  </> : null;
  return (
    <SidebarProvider className="shell" style={{ "--sidebar-width": "272px" } as CSSProperties}>
      <AppSidebar>
        <Button
          className="new-job" variant="default"
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
          <Selector label="작업 상태" isLabelHidden value={filter || "__all"} onChange={value => setFilter(value === "__all" ? "" : value)} options={[
            { value: "__all", label: "전체 상태" }, { value: "active", label: "진행 중" },
            { value: "NEEDS_USER_INPUT", label: "요구사항 확인 필요" }, { value: "FINALIZED", label: "최종 완료" },
            { value: "error", label: "오류" }, { value: "CRITICAL_BLOCKED", label: "명세 진행 중단" },
          ]} />
          <SidebarGroupLabel asChild><h2>
            대화 세션 <span>{filtered.length}</span>
          </h2></SidebarGroupLabel>
          <nav aria-label="작업 기록"><SidebarMenu>
            {!filtered.length && (query || filter) && <li className="history-empty" role="status">조건에 맞는 작업이 없습니다.</li>}
            {filtered.map((item) => <SidebarMenuItem key={item.id}><SessionLink job={item} active={id === item.id} onSelect={() => setSurface("workspace")} /></SidebarMenuItem>)}
          </SidebarMenu></nav>
        </SidebarGroup>
      </AppSidebar>
      <SidebarInset className="workspace-content">
        <Stack direction="horizontal" className="workspace-topbar">
          <SidebarTrigger aria-label="작업 메뉴 접기 또는 펼치기" />
          <h1 title={actualJob?.request}>{surface === "knowledge" ? "지식 검색" : id ? actualJob?.request || "작업 불러오는 중…" : "새 명세 만들기"}</h1>
          {workspaceTabs}
          <Stack direction="horizontal" className="workspace-topbar-status">{actualJob && surface === "workspace" && <StatusIcon status={actualJob.status} />}<ServiceStatusNotice compact /></Stack>
        </Stack>
        <main ref={mainRef}>
          <Notice>{auth.notice || connection}</Notice>
          {surface === "workspace" && <WorkspaceSteps stage={id && !actualJob ? null : workspaceStage(actualJob)} message={workspaceStageMessage(actualJob)} interrupted={!!actualJob && ["error", "interrupted"].includes(actualJob.status)} />}
          {surface === "knowledge" ? (
            <Knowledge selectedJobId={id} />
          ) : (
            <>
              {!id ? (
                <section className="chat-welcome">
                  <h2>만들고 싶은 기능을 알려주세요</h2>
                  <p>완벽하게 정리하지 않아도 괜찮습니다.<br />요청을 바탕으로 필요한 내용을 함께 구체화합니다.</p>
                  <PromptInput id="request-text" label="개발 요청" buttonLabel={decisionSelections.length ? `선택한 결정 ${decisionSelections.length}개와 함께 생성` : "명세 생성 시작"} rows={5} value={request} disabled={blocked}
                    placeholder="예: 팀이 매주 진행 상황을 공유할 수 있는 보고서 생성 기능을 만들어주세요."
                    onChange={(event) => { setRequest(event.target.value); sessionStorage.setItem(draftKey, event.target.value); }} onSend={() => void generate()} />
                  <Stack direction="horizontal" wrap="wrap" className="request-guidance"><span>만들고 싶은 것</span><span>사용할 사람</span><span>지켜야 할 조건</span></Stack>
                  <details className="request-options"><summary>프로젝트와 공통 결정{decisionSelections.length > 0 && <span className="request-selection-count">선택 {decisionSelections.length}개</span>}</summary><ProjectDecisionPicker key={auth.user?.id || "local"} projectId={projectId} onProject={setProjectId} selections={decisionSelections} onSelections={setDecisionSelections} /></details>
                  <p className="subtle">요청과 답변은 명세 생성을 위해 OpenAI에 전송됩니다.</p>
                </section>
              ) : actualJob ? (
                <>
                  <ReusedDecisions key={actualJob.id} jobId={actualJob.id} count={actualJob.reused_decision_count || 0} />
                  {tab !== "conversation" && <CompletedDocuments job={actualJob} select={selectStep} />}
                  <Stack role="tabpanel" id={`workspace-panel-${tab}`} aria-labelledby={`workspace-tab-${tab}`} tabIndex={0} className="workspace-stage-panel" data-view={tab} data-review-open={reviewPanelOpen}>
                  {tab !== "conversation" && (
                    <Stack className="document-action-layout">
                      <section className="document-panel">
                        {detail?.change_review && <details className="document-change-review"><summary><span>명세 변경 검토</span><span>{detail.change_review.changes?.length || 0}건</span></summary><ChangeReview review={detail.change_review} /></details>}
                        {tab === "history" && actualJob.usage && <UsageSummary usage={actualJob.usage} />}
                        {tab === "history" && (
                          <>
                            <ExecutionTimeline key={actualJob.id} job={actualJob} nodes={graphNodes(actualJob)} selected={step} select={session.select} detail={selectedDetail()} />
                            {actualJob.execution_graph?.recording_incomplete && <Notice>일부 이력 기록 누락</Notice>}
                          </>
                        )}
                        {tab !== "history" && <>
                          {detail && !detail.unavailable && !detail.document?.content && <p className="document-empty" role="status">이 단계에는 명세 문서가 없습니다. 아래는 단계 결과입니다.</p>}
                          {selectedDetail()}
                        </>}
                      </section>
                    </Stack>
                  )}
                  {historicalDocument && <aside className="historical-document-notice"><h2>이전 시점의 명세</h2><p>이 문서는 읽기 전용입니다. 현재 검토본에서 수정하거나 승인할 수 있습니다.</p>{currentDocument ? <Button variant="default" onClick={() => selectStep(currentDocument)}>현재 검토본 열기</Button> : <Button onClick={() => setTab("conversation")}>대화에서 현재 상태 확인</Button>}</aside>}
                  {tab === "document" && !historicalDocument && <AstryxButton ref={reviewToggle} className="review-panel-toggle" label={reviewPanelOpen ? "대화와 검토 닫기" : "대화와 검토 열기"} aria-expanded={reviewPanelOpen} aria-controls="workspace-conversation" onClick={() => setReviewPanelOpen(open => !open)} />}
                  <aside id="workspace-conversation" className="workspace-conversation" aria-label={tab === "document" ? "대화와 검토 동작" : "대화"} hidden={tab === "history" || historicalDocument} onKeyDown={event => { if (event.key === "Escape" && reviewPanelOpen && window.innerWidth < 1920) { setReviewPanelOpen(false); reviewToggle.current?.focus(); } }}>
                    {tab === "document" && <AstryxButton ref={reviewClose} className="review-panel-close" label="대화와 검토 닫기" onClick={() => { setReviewPanelOpen(false); reviewToggle.current?.focus(); }} />}
                    {tab === "conversation" && ["queued", "running"].includes(actualJob.status) && <Button disabled={busy} onClick={() => void mutate("stop", undefined).catch(() => {})}>이 작업 중지</Button>}
                    <Conversation key={actualJob.id} job={actualJob} select={selectStep} onAction={mutate} busy={busy} failureDetail={session.failureDetail} documentMode={tab === "document"} appendQuestionRef={appendQuestion} />
                  </aside>
                  </Stack>

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

function WorkspaceSteps({ stage, message, interrupted }: { stage: WorkspaceStage | null; message: string; interrupted: boolean }) {
  const steps: [WorkspaceStage, string][] = [["request", "요청 작성"], ["questions", "질문 답변"], ["review", "명세 검토"], ["final", "최종 확정"]];
  return <nav className="workspace-steps" aria-label="명세 작업 단계"><ol>{steps.map(([key, title], index) => <li key={key} aria-current={stage === key ? "step" : undefined}><span className="workspace-step-number" aria-hidden>{index + 1}</span><span>{title}</span></li>)}</ol>{(!stage || interrupted) && <p role="status">{message}</p>}</nav>;
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
    <details className="completed-documents"><summary>완료 명세와 다운로드</summary><Stack direction="horizontal" wrap="wrap" className="completed-document-controls">
      {(job.latest_completed || job.status === "FINALIZED") && <ImplementationPackage key={`${job.id}:${job.latest_completed?.id || "latest"}`} jobId={job.id} completedId={job.latest_completed?.id} label="최근 승인본 구현 묶음" />}
      <span>
        {job.status === "FINALIZED"
          ? "최근 완료본"
          : job.latest_completed
            ? "현재 작업 중인 초안입니다. 이전 완료본은 별도로 보존됩니다."
            : "아직 승인된 완료 명세가 없습니다."}
      </span>
      {job.latest_completed?.step_id && (
        <Button onClick={() => select(job.latest_completed!.step_id!)}>
          {job.status === "FINALIZED"
            ? "최근 완료 명세 열기"
            : "이전 완료본 열기"}
        </Button>
      )}
      {(job.completed_documents?.length || 0) > 1 && (
        <>
          <Selector label="보존된 완료 명세" isLabelHidden value={selected || job.completed_documents![0].id}
            onChange={setSelected} options={job.completed_documents!.map((d, i) => ({ value: d.id, label: `완료본 ${i + 1}` }))} />
          <Button
            onClick={() => select(selected || job.completed_documents![0].id)}
          >
            선택한 완료본 열기
          </Button>
        </>
      )}
    </Stack></details>
  );
}
