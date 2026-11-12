import { Stack } from "@astryxdesign/core/Stack";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { CheckboxList, CheckboxListItem } from "@astryxdesign/core/CheckboxList";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { RubricReview } from "./RubricReview";
import { ServiceStatusNotice, serviceState } from "../workspace/ServiceStatus";
import { ChangeReview } from "../requirements/ChangeReview";
import { RequirementReview } from "../requirements/RequirementReview";
import { PromptInput, isSubmitShortcut } from "../../shared/ui/PromptInput";
import { ExpandableTextarea } from "../../shared/ui/PromptInput";
import { createPortal } from "react-dom";
import type { ReactNode } from "react";
import { Item, ItemContent, ItemTitle, ItemDescription, ItemActions } from "../../shared/ui/item";
import { SealCheckIcon, LightbulbIcon } from "@phosphor-icons/react";
import { FieldSet, FieldLegend, FieldError } from "../../shared/ui/field";
import { Text } from "@astryxdesign/core/Text";
import { Alert, AlertTitle, AlertDescription } from "../../shared/ui/alert";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "../../shared/ui/collapsible";
import "./question-guidance.css";
import { useEffect, useState, useRef, type RefObject } from "react";
import { useAuth } from "../auth/Auth";
import { Button, Notice } from "../../shared/ui/UI";
import type { Job, QuestionForm, ReviewQuestion, SavedAnswer } from "../../shared/types";
import { array, boolean, requiredObject, text } from "../../shared/api/response-contract";
export function questionDetails(raw: string, index: number) {
  const match = raw.match(/^\[([^\]]+)\]\s*([\s\S]*)$/);
  return {
    id: match?.[1] || `question-${index + 1}`,
    label: match?.[2] || raw,
    raw,
  };
}
type Draft = { ids: string[]; custom: boolean; text: string };
const decodeDraft = requiredObject({ ids: array(text), custom: boolean, text });
export function ReviewContext({ record }: { record?: ReviewQuestion }) {
  if (!record) return null;
  return (
    <Stack className="question-hint">
      {([
        ["requirement_ids", "관련 요구사항"],
        ["missing_information", "미확정 내용"],
        ["resolution_reasons", "결정이 필요한 이유"],
        ["problems", "검토에서 발견한 문제"],
        ["required_changes", "확인이 필요한 이유"],
      ] as const).flatMap(([key, label]) =>
        (record[key] || []).map((text: string, i: number) => (
          <p key={`${key}:${i}`}>
            {label}: {text}
          </p>
        )),
      )}
      {!!record.evidence?.length && <Collapsible><CollapsibleTrigger className="question-evidence-trigger">명세 검토 근거 보기</CollapsibleTrigger><CollapsibleContent>{(record.evidence || []).map((e, i) => (
        <blockquote key={i}>
          관련 명세 ({e.source}): {e.quote}
        </blockquote>
      ))}</CollapsibleContent></Collapsible>}
    </Stack>
  );
}
function initial(form: QuestionForm | undefined, saved?: SavedAnswer): Draft {
  const selection = saved?.selection;
  return form &&
    selection?.form_version === form.form_version &&
    Array.isArray(selection.selected_option_ids)
    ? {
        ids: selection.selected_option_ids,
        custom: selection.custom_text != null,
        text: selection.custom_text || "",
      }
    : { ids: [], custom: !!saved?.answer, text: saved?.answer || "" };
}
export function QuestionActions({
  job,
  onAction,
  busy,
  conversational = false,
  onReview,
  onRequirementReview,
  controlsTarget,
  onAppendFeedback,
  appendFeedbackRef,
}: {
  job: Job;
  onAction: (action: string, payload: unknown) => Promise<void>;
  busy: boolean;
  conversational?: boolean;
  controlsTarget?: HTMLElement | null;
  onAppendFeedback?: (answer: string) => boolean;
  appendFeedbackRef?: RefObject<((text: string) => boolean) | null>;
  onReview?: () => void;
  onRequirementReview?: () => void;
}) {
  const { user, status, publicMode } = useAuth();
  const prefix = `draft:${user?.id || "local"}:${job.id}:`;
  const questions: string[] = job.state?.blocking_questions || [],
    forms: Record<string, QuestionForm> = job.state?.question_forms || {};
  const [drafts, setDrafts] = useState<Record<string, Draft>>({}),
    [feedback, setFeedback] = useState(
      () => sessionStorage.getItem(prefix + "feedback") || "",
    ),
    [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [replayConsent, setReplayConsent] = useState(false);
  const [acceptedCandidate, setAcceptedCandidate] = useState("");
  const reviewKey = `${job.state?.candidate_hash || ""}:${job.state?.rubric_review?.evaluation_hash || ""}`;
  const requiresAcceptance = job.state?.rubric_review?.requires_acceptance === true;
  const [approvedExecution, setApprovedExecution] = useState(() => sessionStorage.getItem(prefix + "approved-execution") || "");
  const submitting = useRef(false);
  const questionFields = useRef<Record<string, HTMLFieldSetElement | null>>({});
  const executionKey = `${job.id}:${job.execution_id}:${job.status}`;
  function appendFeedback(text: string) {
    const value = feedback.trim() ? `${feedback}\n\n${text}` : text;
    if (value.length > 20000) return false;
    setFeedback(value);
    sessionStorage.setItem(prefix + "feedback", value);
    document.getElementById(`feedback-${job.id}`)?.focus();
    return true;
  }
  useEffect(() => {
    if (!appendFeedbackRef) return;
    appendFeedbackRef.current = appendFeedback;
    return () => { appendFeedbackRef.current = null; };
  }, [appendFeedbackRef, feedback, prefix, job.id]);
  useEffect(() => { setReplayConsent(false); }, [executionKey]);
  const disabled = busy || pending || approvedExecution === executionKey || serviceState(publicMode, status).blocked;
  const retryApproval = job.action === "approve" && job.retry_status === "PASS_PENDING_USER_APPROVAL" && !job.read_only;
  const actionClass = conversational ? "action-card conversation-action" : "action-card";
  // 상태는 본문에 유지하고 하단 컨트롤만 포털로 옮긴다.
  const controls = (content: ReactNode) => controlsTarget === undefined ? content : (controlsTarget ? createPortal(content, controlsTarget) : null);
  const questionAnswered = (raw: string, index: number) => {
    const q = questionDetails(raw, index), form = forms[q.id];
    const draft = drafts[`${q.id}:${form?.form_version || "text"}`] || initial(form);
    return draft.ids.length > 0 || ((!form || form.input_type === "text" || draft.custom) && !!draft.text.trim());
  };
  const answeredCount = questions.filter(questionAnswered).length;
  async function perform(action: string, payload: unknown) {
    if (disabled || submitting.current) return false;
    submitting.current = true;
    setPending(true);
    try {
      await onAction(action, payload);
      if (action === "approve") {
        sessionStorage.setItem(prefix + "approved-execution", executionKey);
        setApprovedExecution(executionKey);
      }
      return true;
    } finally { submitting.current = false; setPending(false); }
  }
  const effective = job.retry_status || job.state?.status || job.status;
  const questionKey = questions.join("\0") + JSON.stringify(forms);
  useEffect(() => {
    setDrafts(() => {
      const next: Record<string, Draft> = {};
      questions.forEach((raw, index) => {
        const q = questionDetails(raw, index),
          form = forms[q.id],
          key = `${q.id}:${form?.form_version || "text"}`;
        const saved = (job.state?.saved_answers || []).find(
          (a) => a.question_id === q.id,
        );
        try {
          const stored = sessionStorage.getItem(prefix + key);
          next[key] = stored === null ? initial(form, saved) : decodeDraft(JSON.parse(stored));
        } catch {
          next[key] = initial(form, saved);
        }
      });
      return next;
    });
  }, [prefix, questionKey]);
  function change(key: string, value: Draft) {
    setError("");
    setDrafts((prev) => ({ ...prev, [key]: value }));
    sessionStorage.setItem(prefix + key, JSON.stringify(value));
  }
  async function submit() {
    const answers = [];
    for (const [i, raw] of questions.entries()) {
      const q = questionDetails(raw, i),
        form = forms[q.id],
        draft =
          drafts[`${q.id}:${form?.form_version || "text"}`] || initial(form),
        custom = !form || form.input_type === "text" || draft.custom;
      if (form && draft.custom && !draft.text.trim()) {
        setError("직접 입력 내용을 작성해주세요.");
        return;
      }
      const text = [
        ...(form?.options || [])
          .filter((o) => draft.ids.includes(o.id))
          .map((o) => o.label),
        ...(custom && draft.text.trim() ? [draft.text.trim()] : []),
      ].join("\n");
      if (!text) continue;
      answers.push({
        question_id: q.id,
        question: form?.question || raw,
        answer: text,
        ...(form
          ? {
              selected_option_ids: draft.ids,
              custom_text: custom ? draft.text.trim() : null,
              form_version: form.form_version,
            }
          : {}),
      });
    }
    if (!answers.length) {
      setError("제출할 답변을 하나 이상 입력하세요.");
      return;
    }
    if (!await perform("answer", answers)) return;
    for (const a of answers) {
      const key = `${a.question_id}:${forms[a.question_id]?.form_version || "text"}`;
      sessionStorage.removeItem(prefix + key);
      setDrafts((previous) => {
        const next = { ...previous };
        delete next[key];
        return next;
      });
    }
  }
  if (["error", "interrupted"].includes(job.status))
    return (
      <section className={actionClass} id="job-actions">
        <h3>작업이 중단되었습니다</h3>
        <p>{retryApproval ? "검토가 완료된 명세의 승인을 다시 저장할 수 있습니다." : job.retry_requires_replay
          ? job.retry_kind === "mcp"
            ? "MCP 도구 실행 완료 여부를 확인할 수 없습니다. 다시 실행하면 조회가 중복되고 추가 요금이 발생할 수 있습니다."
            : "이전 단계의 호출 완료 여부를 확인할 수 없습니다. 미완료 단계를 다시 실행하면 이미 성공한 호출도 반복되어 추가 비용이 발생할 수 있습니다."
          : job.can_retry
          ? "저장된 답변을 유지하고 마지막 저장 지점부터 다시 시도합니다."
          : job.retry_unavailable_reason || job.continuation_error || "재시도 가능 여부를 확인할 수 없습니다. 최신 작업 상태를 확인해주세요."}</p>
        {retryApproval && <RubricReview review={job.state?.rubric_review} />}
        {retryApproval && requiresAcceptance && <CheckboxInput label="표시된 남은 결함을 확인했으며, 이 명세에 남아 있는 상태로 수락합니다." value={acceptedCandidate === reviewKey} onChange={checked => setAcceptedCandidate(checked ? reviewKey : "")} />}
        {job.retry_requires_replay && <CheckboxInput label="호출 반복과 추가 비용 가능성을 확인했습니다." value={replayConsent} onChange={setReplayConsent} />}
        <ServiceStatusNotice inline />
        {(job.can_retry || retryApproval) && controls(<Stack direction="horizontal" wrap="wrap" className="chat-answer-controls"><Button
          variant="default" disabled={disabled || (!!job.retry_requires_replay && !replayConsent) || (retryApproval && requiresAcceptance && acceptedCandidate !== reviewKey)}
          onClick={() => void perform(retryApproval ? "approve" : "retry", retryApproval && requiresAcceptance ? { accept_remaining_issues: true } : job.retry_requires_replay ? { replay_pending: true } : null).catch(() => {})}
        >{pending ? "재시도 요청 중…" : retryApproval ? "승인 다시 저장" : job.retry_requires_replay ? "미완료 단계 다시 실행" : "다시 시도"}</Button></Stack>)}
      </section>
    );
  if (job.read_only || (job.status === "FINALIZED" && !job.can_continue))
    return (
      <Notice>
        {job.continuation_error ||
          "이 기록은 열람만 가능합니다. 새 작업을 생성하세요."}
      </Notice>
    );
  if (["running", "queued"].includes(job.status))
    return conversational ? null : (
      <section className={actionClass}>
        <h3>명세를 준비하고 있습니다</h3>
        <p>새로운 결과가 도착하면 자동으로 표시합니다.</p>
        {job.message && <p role="status">{job.message}</p>}
      </section>
    );
  const normalization =
    job.status === "error" &&
    ["REQUIREMENT_NORMALIZATION_FAILED", "SOURCE_COVERAGE_MISSING"].includes(
      job.error_code || "",
    );
  if (["NEEDS_USER_INPUT", "waiting"].includes(effective) && questions.length > 0)
    return (
      <section className={actionClass} id="job-actions" onKeyDown={(event) => {
        if (event.target instanceof HTMLTextAreaElement && isSubmitShortcut(event)) {
          event.preventDefault(); if (!disabled && answeredCount > 0) void submit().catch(() => {});
        }
      }}>
        <span className="eyebrow">NEXT STEP</span>
        <h3>
          {job.state?.awaiting_input_reason === "review"
            ? "요구사항 확인 필요"
            : "답변이 필요한 질문"}
          <span className="question-count">{questions.length}개</span>
        </h3>
        <p>
          답변한 항목만 제출할 수 있습니다. 남은 질문은 다음 단계에서 다시
          표시됩니다.
        </p>
        <nav className="question-navigation" aria-label="질문 탐색"><ol>{questions.map((raw, index) => {
          const question = questionDetails(raw, index), answered = questionAnswered(raw, index);
          return <li key={`${index}:${question.id}`}><AstryxButton className="question-navigation-item" data-answered={answered} label={`질문 ${index + 1} ${answered ? "작성됨" : "미작성"}`} tooltip={question.label} onClick={() => {
            const field = questionFields.current[question.id];
            field?.scrollIntoView?.({ block: "start", behavior: "auto" });
            field?.focus();
          }}><span>{index + 1}</span><span>{answered ? "작성됨" : "미작성"}</span></AstryxButton></li>;
        })}</ol></nav>
        {questions.map((raw, index) => {
          const q = questionDetails(raw, index),
            form = forms[q.id],
            key = `${q.id}:${form?.form_version || "text"}`,
            draft = drafts[key] || initial(form);
          const context = (job.state?.review_questions || []).find(
            (r) => r.question_id === q.id,
          );
          return (
            <FieldSet key={key} ref={element => { questionFields.current[q.id] = element; }} tabIndex={-1} disabled={busy || pending} className="question-form">
              <FieldLegend>
                {index + 1}. {form?.question || q.label}
              </FieldLegend>
              <Stack id={`question-context-${q.id}`} hidden={!context}>
                <Collapsible defaultOpen={!conversational}><CollapsibleTrigger className="question-evidence-trigger">검토 배경 보기</CollapsibleTrigger><CollapsibleContent><ReviewContext record={context} /></CollapsibleContent></Collapsible>
              </Stack>
              {form && form.input_type !== "text" && (form.recommendation !== undefined || form.options.some(option => option.impact)) && <p className="question-guidance-notice">영향과 전제는 모델의 안내입니다. 선택한 항목과 직접 입력한 내용만 답변으로 제출됩니다.</p>}
              {form && form.input_type !== "text" && (() => {
                const options = [...form.options, { id: "__custom", label: "직접 입력", impact: null, assumptions: [] }];
                const selected = [...draft.ids, ...(draft.custom ? ["__custom"] : [])];
                const update = (values: string[]) => change(key, { ...draft, custom: values.includes("__custom"), ids: values.filter(value => value !== "__custom") });
                const description = (option: typeof options[number]) => option.impact || option.assumptions?.length
                  ? <>{option.impact && <p>{option.impact}</p>}{option.assumptions?.map((assumption, n) => <p key={n}>전제: {assumption}</p>)}</> : undefined;
                const label = (option: typeof options[number]) => <>{option.label}{form.recommendation?.option_ids.includes(option.id) && <Text type="supporting" aria-hidden>추천</Text>}{selected.includes(option.id) && <span aria-hidden>선택됨</span>}</>;
                return form.input_type === "single_choice"
                  ? <RadioList label="선택지" isLabelHidden htmlName={key} value={selected[0] || ""} onChange={value => update([value])} isDisabled={busy || pending}>
                    {options.map(option => <RadioListItem key={option.id} value={option.id} label={label(option)} aria-label={option.label} description={description(option)} />)}
                  </RadioList>
                  : <CheckboxList label="선택지" isLabelHidden value={selected} onChange={update} isDisabled={busy || pending}>
                    {options.map(option => <CheckboxListItem key={option.id} value={option.id} label={label(option)} aria-label={option.label} description={description(option)} />)}
                  </CheckboxList>;
              })()}
              {form && form.input_type !== "text" && form.recommendation !== undefined && (form.recommendation ? <Collapsible defaultOpen={!conversational}><CollapsibleTrigger className="question-evidence-trigger">모델 추천 이유와 전제</CollapsibleTrigger><CollapsibleContent><Alert className="question-recommendation" role="note" aria-label="추천 이유와 전제"><LightbulbIcon size={19} aria-hidden /><AlertTitle>모델이 안내한 추천 이유</AlertTitle><AlertDescription><p>{form.recommendation.option_ids.map(id => form.options.find(option => option.id === id)?.label).filter(Boolean).join(" + ")}</p><p>{form.recommendation.reason}</p>{form.recommendation.assumptions.map((assumption, n) => <p key={n}>추천 전제: {assumption}</p>)}<p className="recommendation-boundary">추천과 전제는 안내입니다. 직접 선택하고 답변을 제출해야 결정됩니다.</p></AlertDescription></Alert></CollapsibleContent></Collapsible> : <p className="question-recommendation-unavailable">현재 정보로는 추천을 정하기 어렵습니다</p>)}
              {(!form || form.input_type === "text" || draft.custom) && (
                <ExpandableTextarea
                  disabled={busy || pending}
                  label={`${form?.question || q.label}${form ? " 직접 입력" : ""}`}
                  aria-describedby={
                    context ? `question-context-${q.id}` : undefined
                  }
                  rows={3}
                  maxLength={20000}
                  value={draft.text}
                  onChange={(e) =>
                    change(key, { ...draft, text: e.target.value })
                  }
                />
              )}
            </FieldSet>
          );
        })}
        <ServiceStatusNotice inline />
        {error && <FieldError>{error}</FieldError>}
        {controls(<Stack direction="horizontal" wrap="wrap" className="chat-answer-controls"><span role="status">답변 {answeredCount}/{questions.length}개 작성</span><Button
          variant="default"
          disabled={disabled || answeredCount === 0}
          onClick={() => void submit().catch(() => {})}
        >
          답변 제출
        </Button></Stack>)}
      </section>
    );
  const recovery =
    job.can_continue ||
    normalization ||
    job.retry_action === "revise" ||
    [
      "PASS_PENDING_USER_APPROVAL",
      "waiting_approval",
      "CRITICAL_BLOCKED",
      "blocked",
      "needs_revision",
    ].includes(effective);
  if (!recovery) return null;
  const approval =
    !normalization &&
    ["PASS_PENDING_USER_APPROVAL", "waiting_approval"].includes(effective) &&
    (!job.state || job.state.status === "PASS_PENDING_USER_APPROVAL") &&
    (!job.state?.allowed_actions || job.state.allowed_actions.includes("approve"));
  return (
    <section className={actionClass} id="job-actions"><ServiceStatusNotice inline />
      <span className="eyebrow">NEXT STEP</span>
      <h3>{job.can_continue ? "이어서 요청하기" : "명세 검토와 다음 단계"}</h3>
      {normalization && (
        <Notice>
          요구사항 정리 실패: 답변 부족과는 별개인 내부 처리 문제입니다. 수정
          의견을 유지해 다시 정리할 수 있습니다.
        </Notice>
      )}
      {!approval && job.can_retry && job.state?.allowed_actions?.includes("retry") && <Button disabled={disabled}
        onClick={() => void perform("retry", null).catch(() => {})}>저장된 결과 다시 평가</Button>}
      {approval && <RequirementReview key={`${job.id}:${job.execution_id || job.status}`} jobId={job.id} compact onOpen={onRequirementReview || onReview} />}
      {approval && <ChangeReview key={job.id} review={job.change_review} disabled={disabled || job.read_only || (!!job.state?.plan && !onAppendFeedback)} onQuestion={question => {
        if (job.state?.plan) return onAppendFeedback?.(question) ?? false;
        return appendFeedback(question);
      }} />}
      {approval && <>
        <Item variant="outline" size="sm" className="spec-confirmation">
          <SealCheckIcon weight="duotone" size={25} aria-hidden />
          <ItemContent><ItemTitle>이 명세를 최종 승인할까요?</ItemTitle><ItemDescription>현재 검토본을 확인한 뒤 승인해주세요. 과거 명세를 여는 것만으로 승인되지는 않습니다.</ItemDescription></ItemContent>
        </Item>
        {/* 2026-11-11: 수락 조건과 단일 승인 동작을 같은 하단 영역에 두어 항상 찾을 수 있게 한다. */}
        {controls(<Stack className="chat-approval-controls" role="group" aria-label="명세 승인 동작">
          {requiresAcceptance && <CheckboxInput label="표시된 남은 결함을 확인했으며, 이 명세에 남아 있는 상태로 수락합니다." value={acceptedCandidate === reviewKey} isDisabled={disabled} onChange={checked => setAcceptedCandidate(checked ? reviewKey : "")} />}
          <ItemActions>
            {onReview && <Button onClick={onReview}>현재 검토본 열기</Button>}
            <Button variant="default" disabled={disabled || (requiresAcceptance && acceptedCandidate !== reviewKey)} onClick={() => void perform("approve", requiresAcceptance ? { accept_remaining_issues: true } : null).catch(() => {})}>{approvedExecution === executionKey ? "승인 전송됨" : "이 명세 승인"}</Button>
            {job.state?.rubric_review?.termination && job.state.rubric_review.score < 10 && <Button disabled={disabled} onClick={() => void perform("retry", null).catch(() => {})}>최고점 후보에서 추가 실행</Button>}
          </ItemActions>
        </Stack>)}
      </>}
      {!job.state?.plan && controls(<Stack className="chat-feedback-controls">
      <PromptInput
        id={`feedback-${job.id}`}
        label={job.can_continue ? "추가 요청 내용" : "수정 의견 보내기"}
        buttonLabel={job.can_continue ? "이어서 요청하기" : "수정 요청"}
        rows={3}
        value={feedback}
        disabled={disabled}
        onChange={(event) => { setFeedback(event.target.value); sessionStorage.setItem(prefix + "feedback", event.target.value); }}
        onSend={() => {
          if (!feedback.trim()) { setError("수정 의견을 입력하세요."); return; }
          void perform(job.can_continue ? "continue" : "revise", feedback.trim()).then((sent) => {
            if (!sent) return;
            setFeedback(""); sessionStorage.removeItem(prefix + "feedback");
          }).catch(() => {});
        }}
      />
      <Notice>{error}</Notice></Stack>)}
      <RubricReview review={job.state?.rubric_review} />
    </section>
  );
}
