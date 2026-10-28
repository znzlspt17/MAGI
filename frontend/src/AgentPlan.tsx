import { useRef, useState } from "react";
import { useAuth } from "./Auth";
import { serviceState } from "./ServiceStatus";
import { PromptInput } from "./components/PromptInput";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "./components/ui/collapsible";
import { Button, Notice } from "./UI";
import type { Job, RecordData } from "./types";

const actionLabels: Record<string, string> = {
  project_context: "프로젝트 자료 확인", knowledge_search: "기존 근거 확인", web_research: "조사",
  interview: "요구사항 확인", requirement_lock_stage: "요구사항 정리", spec_compile: "명세 작성·보완",
  checklist_critic: "명세 검토", review_resolution: "해결 방법 판단", compose_candidate: "검토본 준비",
  ask_user: "사용자 결정 확인", blocked: "추가 확인 대기",
};

export function AgentPlan({ job, onDocument }: { job: Job; onDocument?: (stepId: string) => void }) {
  const state = job.state, plan = state?.plan;
  if (!state || !plan?.goal) return null;
  const results = (state.task_results || []) as RecordData[];
  return <Collapsible className="agent-plan" defaultOpen={["running", "queued"].includes(job.status)}>
    <CollapsibleTrigger className="agent-plan-trigger">현재 계획 · {plan.goal}</CollapsibleTrigger>
    <CollapsibleContent className="agent-plan-body">
      <p><strong>{actionLabels[plan.action] || "다음 작업 확인"}</strong></p>
      <p>{plan.reason}</p>
      {!!plan.tasks?.length && <ol>{plan.tasks.map((task: RecordData) => <li key={task.id}>
        {task.title} <span>{({ pending: "예정", completed: "완료", blocked: "확인 필요" } as Record<string, string>)[task.status] || ""}</span>
      </li>)}</ol>}
      {state.stop_reason && <p>{({ repair_limit: "자동 보완 한계", no_progress: "진전 없는 반복", execution_limit: "자동 실행 한도", invalid_plan: "유효한 계획 생성 실패" } as Record<string, string>)[state.stop_reason] || "진행 중단"}</p>}
      {state.wait_reason && <p role="status">{state.wait_reason}</p>}
      {!!results.length && <details><summary>수행한 작업과 근거</summary><ol>{results.map((result, index) => <li key={index}>
        {actionLabels[result.action] || result.action} · 변경 {result.revision + 1} · {result.status === "reused" ? "이전 결과 재사용" : result.action === "interview" ? "확인 작업 완료 · 결정 해결 여부는 질문 상태 참조" : "작업 완료"}<p>{result.reason}</p>
      </li>)}</ol></details>}
      {!!state.document_versions?.length && <p>명세 버전 {state.document_versions.length}개 · 최신 변경 {state.revision + 1}</p>}
      {onDocument && state.document_versions?.map((version: RecordData, index: number) => version.step_id &&
        <Button key={`${index}:${version.hash}`} onClick={() => onDocument(version.step_id)}>명세 버전 {index + 1} 열기</Button>)}
    </CollapsibleContent>
  </Collapsible>;
}

export function AgentComposer({ job, onAction, busy }: {
  job: Job; onAction: (action: string, payload: unknown) => Promise<void>; busy: boolean;
}) {
  const { user, status, publicMode } = useAuth();
  const key = `draft:${user?.id || "local"}:${job.id}:message`;
  const [text, setText] = useState(() => sessionStorage.getItem(key) || "");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const sending = useRef(false);
  const running = ["running", "queued"].includes(job.status);
  const disabled = busy || pending || running || job.read_only || !job.state?.allowed_actions?.includes("message") ||
    serviceState(publicMode, status).blocked;
  async function send(action: string) {
    if (sending.current || disabled || (action === "message" && !text.trim())) return;
    sending.current = true; setPending(true); setError("");
    try {
      await onAction(action, action === "message" ? text.trim() : null);
      if (action === "message") { setText(""); sessionStorage.removeItem(key); }
    } catch (cause) { setError((cause as Error).message); }
    finally { sending.current = false; setPending(false); }
  }
  return <section className="agent-composer" aria-label="대화 입력">
    <PromptInput label="수정 의견 또는 추가 요청" id={`agent-message-${job.id}`} value={text}
      buttonLabel={pending ? "보내는 중…" : "의견 보내기"} disabled={disabled} rows={2}
      onChange={(event) => { setText(event.target.value); sessionStorage.setItem(key, event.target.value); }}
      onSend={() => void send("message")} />
    {running && <p>실행이 끝나면 작성한 의견을 보낼 수 있습니다.</p>}
    {job.state?.allowed_actions?.includes("retry") && <Button disabled={disabled} onClick={() => void send("retry")}>저장된 결과로 추가 실행</Button>}
    {job.status === "CRITICAL_BLOCKED" && <p>{job.state?.stop_reason === "repair_limit"
      ? "이번 보완 횟수를 모두 사용했습니다. 추가 의견 없이 저장된 결과로 추가 실행할 수 있습니다. 초안 수정과 재검토를 진행하며 같은 문제가 남을 수 있습니다."
      : "남은 문제와 보완 내역을 확인하고 수정 의견을 보내거나 추가 실행을 선택해주세요. 입력 변경 없이 추가 실행하면 같은 문제가 남을 수 있습니다."}</p>}
    <Notice>{error}</Notice>
  </section>;
}
