import { useEffect, useRef, useState, type RefObject } from "react";
// shadcn/ui Radix AI Elements Chat / Task compositions (MIT), revision ba1503c64472b82256d9de95e2e62c5901a38e8b.
import { ScalesIcon, FileTextIcon, CaretDownIcon } from "@phosphor-icons/react";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "../../shared/ui/collapsible";
import { Message, MessageContent, MessageHeader, MessageFooter } from "../../shared/ui/message";
import { Bubble, BubbleContent } from "../../shared/ui/bubble";
import { MessageScrollerProvider, MessageScroller, MessageScrollerViewport, MessageScrollerContent, MessageScrollerItem, MessageScrollerButton } from "../../shared/ui/message-scroller";
import { conversationTurns } from "./conversation-data";
import { QuestionActions, questionDetails } from "./QuestionActions";
import { Button, Notice, formatTime } from "../../shared/ui/UI";
import type { Job } from "../../shared/types";
import { AgentPlan, AgentComposer } from "../workspace/AgentPlan";
import { ExecutionMonitor } from "../execution/ExecutionMonitor";
import { FailureDiagnostic } from "../execution/FailureDiagnostic";
import { DetailNotices } from "../execution/DetailNotices";
import type { StepDetail } from "../execution/execution-detail";
import { useAuth } from "../auth/Auth";

type ConversationProps = { job: Job; select: (stepId: string, requirements?: boolean) => void; onAction: (action: string, payload: unknown) => Promise<void>; busy: boolean; failureDetail?: StepDetail | null; documentMode?: boolean; appendQuestionRef?: RefObject<((text: string) => boolean) | null> };
export function Conversation(props: ConversationProps) {
  const { user } = useAuth();
  const draftKey = `draft:${user?.id || "local"}:${props.job.id}:message`;
  return <ConversationContent key={draftKey} {...props} draftKey={draftKey} />;
}
function ConversationContent({ job, select, onAction, busy, draftKey, failureDetail, documentMode = false, appendQuestionRef }: ConversationProps & { draftKey: string }) {
  const [message, setMessage] = useState(() => sessionStorage.getItem(draftKey) || "");
  const [composerOpen, setComposerOpen] = useState(false);
  const focusComposer = useRef(false);
  function updateMessage(value: string) {
    setMessage(value);
    if (value) sessionStorage.setItem(draftKey, value);
    else sessionStorage.removeItem(draftKey);
  }
  function appendMessage(answer: string) {
    const value = message.trim() ? `${message}\n\n${answer}` : answer;
    if (value.length > 20000) return false;
    updateMessage(value);
    if (["NEEDS_USER_INPUT", "waiting"].includes(job.state?.status || job.status)) {
      focusComposer.current = true;
      setComposerOpen(true);
    } else document.getElementById(`agent-message-${job.id}`)?.focus();
    return true;
  }
  useEffect(() => {
    if (composerOpen && focusComposer.current) {
      document.getElementById(`agent-message-${job.id}`)?.focus();
      focusComposer.current = false;
    }
  }, [composerOpen, job.id, message]);
  const messageDraft = { value: message, onChange: updateMessage };
  const appendFeedbackRef = useRef<((text: string) => boolean) | null>(null);
  useEffect(() => {
    if (!appendQuestionRef) return;
    appendQuestionRef.current = question => {
      if (busy || job.read_only || ["queued", "running"].includes(job.status)) return false;
      return job.state?.plan ? appendMessage(question) : appendFeedbackRef.current?.(question) ?? false;
    };
    return () => { appendQuestionRef.current = null; };
  }, [appendQuestionRef, job.id, job.status, job.read_only, job.state?.plan, job.state?.status, busy, message]);
  const [controlsTarget, setControlsTarget] = useState<HTMLDivElement | null>(null);
  const root = useRef<HTMLElement>(null);
  const scrollPositions = useRef({ conversation: 0, document: 0 });
  useEffect(() => {
    const viewport = root.current?.querySelector<HTMLElement>(".chat-viewport");
    if (!viewport) return;
    const key = documentMode ? "document" : "conversation";
    viewport.scrollTop = scrollPositions.current[key];
    return () => { scrollPositions.current[key] = viewport.scrollTop; };
  }, [documentMode]);
  useEffect(() => {
    const shell = root.current?.closest<HTMLElement>(".shell");
    const viewport = window.visualViewport;
    if (!shell || !viewport) return;
    // 모바일 키보드가 열린 경우에도 제출 영역을 보이는 높이 안에 둔다.
    const resize = () => shell.style.setProperty("--chat-viewport-height", `${viewport.height}px`);
    resize();
    viewport.addEventListener("resize", resize);
    return () => { viewport.removeEventListener("resize", resize); shell.style.removeProperty("--chat-viewport-height"); };
  }, []);
  const { turns, incomplete } = conversationTurns(job);
  const latestEventId = job.session_events?.at(-1)?.id;
  const waiting = !["error", "interrupted"].includes(job.status) && ["NEEDS_USER_INPUT", "waiting"].includes(job.state?.status || job.status);
  const reviewStep = [...(job.execution_graph?.nodes || [])].reverse().find((node) => node.has_document && (!job.execution_id || !node.execution_id || node.execution_id === job.execution_id))?.id;
  return <section ref={root} className="chat-workspace" aria-label="MAGI 대화">
    <MessageScrollerProvider autoScroll={!documentMode} defaultScrollPosition={documentMode ? "start" : "end"} scrollEdgeThreshold={48}>
      <MessageScroller className="chat-scroll-root">
        <MessageScrollerViewport className="chat-viewport" aria-label="대화 이력">
          <MessageScrollerContent className="chat-messages">
            {incomplete && <MessageScrollerItem className="conversation-history-item" messageId="history-missing"><Notice>이전 대화의 상세 기록이 없습니다. 저장된 요청과 현재 상태만 표시합니다.</Notice></MessageScrollerItem>}
            {turns.map((turn) => <MessageScrollerItem className="conversation-history-item" key={turn.id} messageId={turn.id} scrollAnchor={turn.role === "user"}>
              <Message align={turn.role === "user" ? "end" : "start"} className={`chat-turn ${turn.role}`}>
                <MessageContent>
                  <MessageHeader>{turn.role === "user" ? "나" : <><ScalesIcon weight="duotone" size={18} aria-hidden />MAGI</>}</MessageHeader>
                  <Bubble align={turn.role === "user" ? "end" : "start"} variant={turn.role === "user" ? "tinted" : "ghost"}><BubbleContent>
                    {turn.text && <p className="chat-message-text">{turn.text}</p>}
                    {turn.answers?.map((answer, index) => <div className="chat-answer" key={`${index}:${answer.question_id || "answer"}`}>
                      <p className="chat-message-text">{answer.answer}</p>
                      {answer.question?.trim() && <Collapsible className="chat-question-reference">
                        <CollapsibleTrigger className="chat-question-trigger">답변 대상 질문<CaretDownIcon size={14} aria-hidden /></CollapsibleTrigger>
                        <CollapsibleContent><blockquote className="chat-question-text">{answer.question}</blockquote></CollapsibleContent>
                      </Collapsible>}
                    </div>)}
                    {!!turn.questions?.length && !(waiting && turn.eventId === latestEventId) && <ol className="chat-history-questions">{turn.questions.map((question, index) => <li key={`${index}:${question}`}>{questionDetails(question, index).label}</li>)}</ol>}
                    {turn.documentStepId && <Button className="chat-document-link" onClick={() => select(turn.documentStepId!)}><FileTextIcon size={17} aria-hidden />이 시점의 명세 열기</Button>}
                  </BubbleContent></Bubble>
                  {turn.timestamp && <MessageFooter>{formatTime(turn.timestamp)}</MessageFooter>}
                </MessageContent>
              </Message>
            </MessageScrollerItem>)}
            <MessageScrollerItem className="conversation-history-item" messageId="current-plan"><AgentPlan job={job} onDocument={select} /></MessageScrollerItem>
            <MessageScrollerItem className="conversation-history-item" messageId="current-state"><ExecutionMonitor job={job} select={select} /></MessageScrollerItem>
            {job.status === "error" && failureDetail && <MessageScrollerItem className="conversation-history-item" messageId="failure-diagnostic">
              {failureDetail.unavailable && <Notice>실패 상세를 불러오지 못했습니다. 화면을 새로고침해 다시 확인하세요.</Notice>}
              <FailureDiagnostic value={failureDetail.result?.diagnostic} retry={job} />
              <DetailNotices detail={failureDetail} />
            </MessageScrollerItem>}
            <MessageScrollerItem messageId="current-actions"><Message align="start" className="chat-turn magi"><MessageContent><QuestionActions key={job.id} job={job} onAction={onAction} busy={busy} conversational controlsTarget={controlsTarget} onAppendFeedback={appendMessage} appendFeedbackRef={appendFeedbackRef} onReview={reviewStep ? () => select(reviewStep) : undefined} onRequirementReview={reviewStep ? () => select(reviewStep, true) : undefined} /></MessageContent></Message></MessageScrollerItem>
          </MessageScrollerContent>
        </MessageScrollerViewport>
        {!documentMode && <MessageScrollerButton size="sm" className="chat-latest">최신 메시지로 이동</MessageScrollerButton>}
      </MessageScroller>
    </MessageScrollerProvider>
    <div className="chat-actions" ref={setControlsTarget} />
    {job.state?.plan && (waiting ? <Collapsible className="chat-secondary-composer" open={composerOpen} onOpenChange={setComposerOpen}>
      <CollapsibleTrigger className="chat-question-trigger">수정 의견 또는 추가 요청<CaretDownIcon size={14} aria-hidden /></CollapsibleTrigger>
      <CollapsibleContent><AgentComposer key={job.id} job={job} onAction={onAction} busy={busy} draft={messageDraft} /></CollapsibleContent>
    </Collapsible> : <AgentComposer key={job.id} job={job} onAction={onAction} busy={busy} draft={messageDraft} />)}
  </section>;
}
