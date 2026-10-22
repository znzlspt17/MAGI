// shadcn/ui Radix AI Elements Chat / Task compositions (MIT), revision ba1503c64472b82256d9de95e2e62c5901a38e8b.
import { ScalesIcon, FileTextIcon, CheckCircleIcon, WarningCircleIcon, CircleNotchIcon, ClockIcon, QuestionIcon, CaretDownIcon } from "@phosphor-icons/react";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "./components/ui/collapsible";
import { Message, MessageContent, MessageHeader, MessageFooter } from "./components/ui/message";
import { Bubble, BubbleContent } from "./components/ui/bubble";
import { MessageScrollerProvider, MessageScroller, MessageScrollerViewport, MessageScrollerContent, MessageScrollerItem, MessageScrollerButton } from "./components/ui/message-scroller";
import { Trace, TraceCollapsible, TraceCollapsibleContent, TraceCollapsibleTrigger, TraceLine, TraceIcon, TraceTitle } from "./components/ui/trace";
import { conversationTurns } from "./conversation-data";
import { QuestionActions, questionDetails } from "./QuestionActions";
import { Button, Notice, formatTime, statusLabel } from "./UI";
import type { Job } from "./types";

export function Conversation({ job, select, onAction, busy }: { job: Job; select: (stepId: string, requirements?: boolean) => void; onAction: (action: string, payload: unknown) => Promise<void>; busy: boolean }) {
  const { turns, incomplete } = conversationTurns(job);
  const latestEventId = job.session_events?.at(-1)?.id;
  const waiting = ["NEEDS_USER_INPUT", "waiting"].includes(job.retry_status || job.state?.status || job.status);
  const running = ["queued", "running"].includes(job.status);
  const failed = ["error", "failed", "interrupted", "CRITICAL_BLOCKED", "blocked"].includes(job.status);
  const StatusIcon = running ? CircleNotchIcon : failed ? WarningCircleIcon : ["FINALIZED", "completed"].includes(job.status) ? CheckCircleIcon : waiting || ["PASS_PENDING_USER_APPROVAL", "waiting_approval"].includes(job.status) ? QuestionIcon : ClockIcon;
  const reviewStep = [...(job.execution_graph?.nodes || [])].reverse().find((node) => node.has_document && (!job.execution_id || !node.execution_id || node.execution_id === job.execution_id))?.id;
  return <section className="chat-workspace" aria-label="MAGI 대화">
    <MessageScrollerProvider autoScroll defaultScrollPosition="end" scrollEdgeThreshold={48}>
      <MessageScroller className="chat-scroll-root">
        <MessageScrollerViewport className="chat-viewport" aria-label="대화 이력">
          <MessageScrollerContent className="chat-messages">
            {incomplete && <MessageScrollerItem messageId="history-missing"><Notice>이전 대화의 상세 기록이 없습니다. 저장된 요청과 현재 상태만 표시합니다.</Notice></MessageScrollerItem>}
            {turns.map((turn) => <MessageScrollerItem key={turn.id} messageId={turn.id} scrollAnchor={turn.role === "user"}>
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
            <MessageScrollerItem messageId="current-state"><Trace className="chat-task"><TraceCollapsible defaultOpen={running || failed}>
              <TraceCollapsibleTrigger><TraceLine status={running ? "running" : failed ? "error" : undefined}><TraceIcon><StatusIcon size={17} aria-hidden /></TraceIcon><TraceTitle>{statusLabel(job.status)}</TraceTitle></TraceLine></TraceCollapsibleTrigger>
              <TraceCollapsibleContent><p>{job.message || (waiting ? "아래에서 답변할 항목을 선택하고 작성해주세요." : "저장된 현재 작업 상태입니다.")}</p></TraceCollapsibleContent>
            </TraceCollapsible></Trace></MessageScrollerItem>
          </MessageScrollerContent>
        </MessageScrollerViewport>
        <MessageScrollerButton size="sm" className="chat-latest">최신 메시지로 이동</MessageScrollerButton>
      </MessageScroller>
    </MessageScrollerProvider>
    <div className="chat-actions"><QuestionActions key={job.id} job={job} onAction={onAction} busy={busy} conversational onReview={reviewStep ? () => select(reviewStep) : undefined} onRequirementReview={reviewStep ? () => select(reviewStep, true) : undefined} /></div>
  </section>;
}
