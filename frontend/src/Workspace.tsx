import { ExecutionTimeline, ResearchResult } from "./ExecutionTimeline";
import { ChangeReview } from "./ChangeReview";
import { ServiceStatusNotice, serviceState } from "./ServiceStatus";
import { Conversation } from "./Conversation";
import { PromptInput } from "./components/PromptInput";
import { Tabs, TabsList, TabsTrigger } from "./components/ui/tabs";
import { Badge } from "./components/ui/badge";
import { AppSidebar } from "./components/AppSidebar";
import { SidebarProvider, SidebarInset, SidebarTrigger, SidebarGroup, SidebarGroupLabel, SidebarMenu, SidebarMenuItem, SidebarMenuButton } from "./components/ui/sidebar";
import { Input } from "./components/ui/input";
import { PlusIcon, SquaresFourIcon, GraphIcon, SparkleIcon, FileTextIcon, ChatCircleDotsIcon, ClockCounterClockwiseIcon } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, post } from "./api";
import { useAuth } from "./Auth";
import { Button, Notice, statusLabel, formatTime, usageLabel } from "./UI";
import { DocumentView } from "./DocumentView";
import { ProjectDecisionPicker, ReusedDecisions, type DecisionSelection } from "./ProjectDecisions";
import { ImplementationPackage } from "./ImplementationPackage";
import { questionDetails } from "./QuestionActions";
import Knowledge from "./Knowledge";
import type { Job, RecordData, Step } from "./types";
export function graphNodes(job: Job): Step[] {
  if (job.execution_graph?.nodes?.length) return job.execution_graph.nodes;
  return [
    {
      id: "legacy",
      stage: "request",
      status: job.status,
      summary: job.message || job.request,
      has_document: !!(job.final || job.candidate),
      detail_available: true,
    },
  ];
}
const stageLabel = (node?: Step) =>
  node?.title ||
  {
    request: "요청 접수",
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
    critical_report: "명세 보완 실패 보고",
  }[node?.stage || ""] ||
  "실행 단계";
function legacyDetail(job: Job) {
  return {
    result: {
      summary: job.message,
      questions: job.state?.blocking_questions,
      report: job.critical,
    },
    document:
      job.final || job.candidate
        ? {
            content: job.final || job.candidate,
            filename: job.final
              ? "FINAL_AGENT_SPEC.md"
              : "approval_candidate_spec.en.md",
          }
        : null,
  };
}
export default function Workspace() {
  const auth = useAuth(),
    navigate = useNavigate(),
    location = useLocation(),
    { id } = useParams();
  const [connectionEpoch, setConnectionEpoch] = useState(0);
  useEffect(() => {
    const resume = (event: PageTransitionEvent) => {
      if (event.persisted) setConnectionEpoch((value) => value + 1);
    };
    window.addEventListener("pageshow", resume);
    return () => window.removeEventListener("pageshow", resume);
  }, []);
  const [jobs, setJobs] = useState<Job[]>([]),
    [job, setJob] = useState<Job | null>(null),
    [surface, setSurface] = useState("workspace"),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useState(""),
    [busy, setBusy] = useState(false),
    [refreshIndex, setRefreshIndex] = useState(0),
    [tab, setTab] = useState("conversation"),
    [step, setStep] = useState(""),
    [detail, setDetail] = useState<RecordData | null>(null),
    [loading, setLoading] = useState(false),
    [connection, setConnection] = useState("");
  const manual = useRef(false),
    views = useRef(
      new Map<string, { step: string; tab: string; manual: boolean }>(),
    ),
    fetchSequence = useRef(0),
    selectedId = useRef(id),
    navigation = useRef(location.key),
    mutating = useRef(false);
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
  const refresh = useCallback(() => setRefreshIndex((i) => i + 1), []);
  useEffect(() => {
    let alive = true,
      inFlight = false,
      pending = false,
      controller: AbortController | null = null;
    const load = async () => {
      if (inFlight) {
        pending = true;
        return;
      }
      inFlight = true;
      controller = new AbortController();
      try {
        const list = await api<Job[]>("/api/jobs", {
          signal: controller.signal,
        });
        if (alive) setJobs(list);
      } catch (e) {
        if (alive && (e as Error).name !== "AbortError")
          auth.setNotice((e as Error).message);
      } finally {
        inFlight = false;
        if (alive && pending) {
          pending = false;
          void load();
        }
      }
    };
    let socket: WebSocket | null = null,
      reconnect: ReturnType<typeof setTimeout> | undefined,
      attempt = 0;
    const connect = () => {
      if (!alive) return;
      socket = new WebSocket(
        `${locationProtocol()}//${window.location.host}/ws/events`,
      );
      socket.onopen = () => {
        if (alive) {
          window.dispatchEvent(new Event("service-status"));
          attempt = 0;
          setConnection("");
          void load();
          refresh();
        }
      };
      socket.onmessage = (event) => {
        if (!alive) return;
        let value;
        try {
          value = JSON.parse(event.data);
        } catch {
          return;
        }
        if (["ready", "job.changed"].includes(value.event)) {
          void load();
          refresh();
        } else if (value.event === "records.deleted") {
          for (const deletedId of value.ids || []) {
            views.current.delete(deletedId);
            const prefix =
              "draft:" +
              (auth.user?.id || "local") +
              ":" +
              deletedId +
              ":";
            Object.keys(sessionStorage)
              .filter((key) => key.startsWith(prefix))
              .forEach((key) => sessionStorage.removeItem(key));
          }
          if ((value.ids || []).includes(selectedId.current)) navigate("/");
          window.dispatchEvent(new Event("cleanup"));
          void load();
          refresh();
        } else if (value.event === "service.status")
          window.dispatchEvent(
            new CustomEvent("service-status", { detail: value.status }),
          );
        else if (value.event === "server_error") socket?.close();
      };
      socket.onclose = () => {
        if (!alive) return;
        setConnection("작업 서버 연결이 끊어졌습니다. 재연결 중입니다.");
        reconnect = setTimeout(
          connect,
          [1000, 2000, 4000, 8000, 10000][Math.min(attempt++, 4)],
        );
      };
      socket.onerror = () => socket?.close();
    };
    void load();
    connect();
    const poll = setInterval(() => {
      void load();
      refresh();
    }, 15000);
    const pagehide = () => {
      alive = false;
      clearTimeout(reconnect);
      clearInterval(poll);
      socket?.close();
      controller?.abort();
    };
    window.addEventListener("pagehide", pagehide);
    return () => {
      pagehide();
      window.removeEventListener("pagehide", pagehide);
    };
  }, [auth.user?.id, connectionEpoch]);
  useEffect(() => {
    setJob(null);
    setDetail(null);
    manual.current = false;
    const saved = id ? views.current.get(id) : null;
    setStep(saved?.step || "");
    setTab(saved?.tab || "conversation");
    manual.current = saved?.manual || false;
    setSurface("workspace");
  }, [id]);
  useEffect(() => {
    if (!id) return;
    let alive = true;
    const sequence = ++fetchSequence.current,
      controller = new AbortController();
    setLoading(true);
    api<Job>(`/api/jobs/${encodeURIComponent(id)}`, {
      signal: controller.signal,
    })
      .then((value) => {
        if (!alive || sequence !== fetchSequence.current) return;
        setJob(value);
        if (
          !["queued", "running"].includes(value.status) &&
          [
            "작업을 대기열에 넣었습니다.",
            "새 작업을 대기열에 넣었습니다.",
          ].includes(auth.notice)
        )
          auth.setNotice("");
        setStep((previous) => {
          const nodes = graphNodes(value),
            exists =
              nodes.some((n) => n.id === previous) ||
              (value.completed_documents || []).some(
                (n: Step) => n.id === previous,
              );
          if (manual.current && exists) return previous;
          const requestedCompleted = new URLSearchParams(location.search).get("completed_id");
          if (requestedCompleted && (value.completed_documents || []).some((d: Step) => d.id === requestedCompleted)) {
            manual.current = true; setTab("document"); return requestedCompleted;
          }
          const doc = [...nodes].reverse().find((n) => n.has_document);
          return (doc || nodes.at(-1))?.id || "";
        });
      })
      .catch((e) => {
        if (alive && e.name !== "AbortError") auth.setNotice(e.message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
      controller.abort();
    };
  }, [id, refreshIndex, location.search]);
  const node =
    job &&
    [...graphNodes(job), ...(job.completed_documents || [])].find(
      (n) => n.id === step,
    );
  const nodeSignature = JSON.stringify(node);
  useEffect(() => {
    if (!job || job.id !== id || !step) return;
    let alive = true;
    const controller = new AbortController();
    setDetail(null);
    if (!job.execution_graph?.nodes) {
      setDetail(legacyDetail(job));
      return;
    }
    if (!node?.detail_available) {
      setDetail({
        unavailable: true,
        message: "이 단계의 상세 기록이 저장되지 않았습니다.",
      });
      return;
    }
    api(
      `/api/jobs/${encodeURIComponent(id!)}/steps/${encodeURIComponent(step)}`,
      { signal: controller.signal },
    )
      .then((value) => {
        if (alive) setDetail(value.step || value.detail || value);
      })
      .catch((e) => {
        if (alive && e.name !== "AbortError")
          setDetail({ unavailable: true, message: e.message });
      });
    return () => {
      alive = false;
      controller.abort();
    };
  }, [id, step, nodeSignature]);
  useEffect(() => {
    if (id && job?.id === id) views.current.set(id, { step, tab, manual: manual.current });
  }, [id, job?.id, step, tab]);
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
    manual.current = true;
    setEvidenceOnly(requirements);
    setStep(value);
    setTab("document");
  }
  async function mutate(action: string, payload: unknown) {
    if (!id || mutating.current) return;
    mutating.current = true;
    setBusy(true);
    const target = id;
    try {
      await post(`/api/jobs/${encodeURIComponent(id)}/${action}`, {
        payload,
        execution_id: job?.execution_id,
      });
      if (selectedId.current === target) {
        auth.setNotice("작업을 대기열에 넣었습니다.");
        refresh();
      }
    } catch (e) {
      if (action !== "message") auth.setNotice((e as Error).message);
      throw e;
    } finally {
      mutating.current = false;
      setBusy(false);
      void auth.refreshStatus().catch(() => {});
    }
  }
  async function generate() {
    if (mutating.current) return;
    if (!request.trim()) {
      auth.setNotice("개발 요청을 입력하세요.");
      return;
    }
    mutating.current = true;
    setBusy(true);
    const submitted = navigation.current;
    try {
      const value = await post<Job>("/api/jobs", {
        request: request.trim(),
        provider: "openai",
        project_id: projectId || null,
        decision_reuse: decisionSelections,
      });
      if (submitted === navigation.current) {
        setRequest("");
        setDecisionSelections([]);
        sessionStorage.removeItem(draftKey);
        navigate(`/jobs/${value.id}`);
      }
      setJobs((previous) => [
        value,
        ...previous.filter((j) => j.id !== value.id),
      ]);
      auth.setNotice("새 작업을 대기열에 넣었습니다.");
      refresh();
    } catch (e) {
      auth.setNotice((e as Error).message);
    } finally {
      mutating.current = false;
      setBusy(false);
    }
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
            disabled={!!(auth.status.busy && !auth.status.mine)}
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
            <option value="CRITICAL_BLOCKED">명세 보완 실패</option>
          </select>
          <SidebarGroupLabel asChild><h2>
            대화 세션 <span>{filtered.length}</span>
          </h2></SidebarGroupLabel>
          <nav aria-label="작업 기록"><SidebarMenu>
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
              <h1>{surface === "knowledge" ? "지식 검색" : id ? actualJob?.request?.slice(0, 70) || "작업 불러오는 중…" : "아이디어의 다음 문장을 함께."}</h1>
              {!id && surface === "workspace" && <p>만들고 싶은 것을 들려주세요. 필요한 질문부터 명세 완성까지 함께합니다.</p>}
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
                  <div className="welcome-mark"><SparkleIcon weight="duotone" size={38} aria-hidden /></div>
                  <h2>무엇을 만들고 싶으신가요?</h2>
                  <p>완벽하게 정리하지 않아도 괜찮습니다.<br />요청을 바탕으로 필요한 내용을 함께 구체화합니다.</p>
                  <ServiceStatusNotice inline />
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
                    <Conversation key={actualJob.id} job={actualJob} select={selectStep} onAction={mutate} busy={busy} />
                  ) : (
                    <div className="document-action-layout">
                      <section className="document-panel">
                        <ChangeReview review={detail?.change_review} />
                        {tab === "history" && actualJob.usage && <p className="subtle">{usageLabel(actualJob.usage)}</p>}
                        {tab === "history" && (
                          <>
                            <ExecutionTimeline key={actualJob.id} job={actualJob} nodes={graphNodes(actualJob)} selected={step} select={selected => { manual.current = true; setStep(selected); }} />
                            {actualJob.execution_graph?.recording_incomplete && <Notice>일부 이력 기록 누락</Notice>}
                          </>
                        )}
                        {detail?.unavailable ? (
                          <Notice>기록 확인 불가: {detail.message}</Notice>
                        ) : !detail ? (
                          <p role="status">
                            {loading ? "작업" : "단계 상세"}를 불러오는
                            중입니다.
                          </p>
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
                        ) : (
                          <StepResult node={node} detail={detail} hideQuestions={!!actualJob.session_events?.find(event => event.id === node?.execution_id)?.questions?.length && JSON.stringify(actualJob.session_events?.find(event => event.id === node?.execution_id)?.questions) === JSON.stringify(detail?.result?.questions || detail?.result?.blocking_questions || [])} />
                        )}
                        {(result.issues?.length ||
                          result.resolved_issues?.length ||
                          result.report) && <Issues result={result} />}
                      </section>
                      <aside className="action-panel">
                        <section className="action-card document-chat-cta"><h3>대화에서 다음 단계를 진행하세요</h3><p>답변·수정·승인은 대화의 최신 상태에서만 진행할 수 있습니다.</p><Button className="primary" onClick={showConversation}><ChatCircleDotsIcon size={18} aria-hidden />대화에서 답변하기</Button></section>
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
function locationProtocol() {
  return window.location.protocol === "https:" ? "wss:" : "ws:";
}
function Account() {
  const auth = useAuth(),
    [remaining, setRemaining] = useState<number | null>(null),
    location = useLocation();
  useEffect(() => {
    const update = () =>
      setRemaining(
        auth.status.deadline
          ? Math.max(0, Math.ceil(auth.status.deadline - Date.now() / 1000))
          : null,
      );
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [auth.status.deadline]);
  async function lease(action: string) {
    try {
      await post(
        `/api/lease/${action}`,
        action === "resume" ? { id: location.pathname.split("/").pop() } : {},
      );
      await auth.refreshStatus();
    } catch (e) {
      auth.setNotice((e as Error).message);
    }
  }
  return (
    <header className="account-header">
      <SidebarTrigger  className="desktop-sidebar-trigger" />
      <ServiceStatusNotice />
      {remaining !== null && remaining <= 30 && (
        <p role="alert">곧 사용권이 해제됩니다.</p>
      )}
      <div className="account-controls">
        {auth.status.mine && auth.status.phase === "waiting" && auth.status.checkState === "ready" && (
          <>
            <Button onClick={() => void lease("keep")}>계속 사용</Button>
            <Button onClick={() => void lease("release")}>사용 종료</Button>
          </>
        )}
        {auth.publicMode &&
          auth.status.checkState === "ready" && !auth.status.busy &&
          location.pathname.startsWith("/jobs/") && (
            <Button onClick={() => void lease("resume")}>
              이 작업 사용권 다시 얻기
            </Button>
          )}
      </div>
    </header>
  );
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
    <div className="completed-documents">
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
    </div>
  );
}
function StepResult({ node, detail, hideQuestions = false }: { node?: Step; detail: RecordData; hideQuestions?: boolean }) {
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
function Issues({ result }: { result: RecordData }) {
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
    <details className="issues">
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
