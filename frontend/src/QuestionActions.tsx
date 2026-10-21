import { ServiceStatusNotice, serviceState } from "./ServiceStatus";
import { ChangeReview } from "./ChangeReview";
import { PromptInput, isSubmitShortcut } from "./components/PromptInput";
import { InputGroup, InputGroupTextarea } from "./components/ui/input-group";
import { Item, ItemContent, ItemTitle, ItemDescription, ItemActions } from "./components/ui/item";
import { SealCheckIcon } from "@phosphor-icons/react";
import { useEffect, useState, useRef } from "react";
import { useAuth } from "./Auth";
import { Button, Notice } from "./UI";
import type { Job, QuestionForm, RecordData } from "./types";
export function questionDetails(raw: string, index: number) {
  const match = raw.match(/^\[([^\]]+)\]\s*([\s\S]*)$/);
  return {
    id: match?.[1] || `question-${index + 1}`,
    label: match?.[2] || raw,
    raw,
  };
}
type Draft = { ids: string[]; custom: boolean; text: string };
export function ReviewContext({ record }: { record?: RecordData }) {
  if (!record) return null;
  return (
    <div className="question-hint">
      {[
        ["requirement_ids", "관련 요구사항"],
        ["missing_information", "미확정 내용"],
        ["resolution_reasons", "결정이 필요한 이유"],
        ["problems", "검토에서 발견한 문제"],
        ["required_changes", "확인이 필요한 이유"],
      ].flatMap(([key, label]) =>
        (record[key] || []).map((text: string, i: number) => (
          <p key={`${key}:${i}`}>
            {label}: {text}
          </p>
        )),
      )}
      {(record.evidence || []).map((e: RecordData, i: number) => (
        <blockquote key={i}>
          관련 명세 ({e.source}): {e.quote}
        </blockquote>
      ))}
    </div>
  );
}
function initial(form: QuestionForm | undefined, saved?: RecordData): Draft {
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
}: {
  job: Job;
  onAction: (action: string, payload: unknown) => Promise<void>;
  busy: boolean;
  conversational?: boolean;
  onReview?: () => void;
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
  const [approvedExecution, setApprovedExecution] = useState(() => sessionStorage.getItem(prefix + "approved-execution") || "");
  const submitting = useRef(false);
  const executionKey = `${job.id}:${job.execution_id || "legacy"}:${job.status}`;
  const disabled = busy || pending || approvedExecution === executionKey || serviceState(publicMode, status).blocked;
  const actionClass = conversational ? "action-card conversation-action" : "action-card";
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
          (a: RecordData) => a.question_id === q.id,
        );
        try {
          next[key] =
            JSON.parse(sessionStorage.getItem(prefix + key) || "null") ||
            initial(form, saved);
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
      job.error_code,
    );
  if (["NEEDS_USER_INPUT", "waiting"].includes(effective))
    return (
      <section className={actionClass} id="job-actions" onKeyDown={(event) => {
        if (event.target instanceof HTMLTextAreaElement && isSubmitShortcut(event)) {
          event.preventDefault(); if (!disabled) void submit().catch(() => {});
        }
      }}>
        <span className="eyebrow">NEXT STEP</span>
        <h3>
          {job.state?.awaiting_input_reason === "review"
            ? "요구사항 확인 필요"
            : "답변이 필요한 질문"}{" "}
          · {questions.length}개
        </h3>
        <p>
          답변한 항목만 제출할 수 있습니다. 남은 질문은 다음 단계에서 다시
          표시됩니다.
        </p>
        {questions.map((raw, index) => {
          const q = questionDetails(raw, index),
            form = forms[q.id],
            key = `${q.id}:${form?.form_version || "text"}`,
            draft = drafts[key] || initial(form);
          const context = (job.state?.review_questions || []).find(
            (r: RecordData) => r.question_id === q.id,
          );
          return (
            <fieldset key={key} disabled={busy || pending} className="question-form">
              <legend>
                {index + 1}. {form?.question || q.label}
              </legend>
              <div id={`question-context-${q.id}`}>
                <ReviewContext record={context} />
              </div>
              {form &&
                form.input_type !== "text" &&
                [...form.options, { id: "__custom", label: "직접 입력" }].map(
                  (option) => (
                    <label key={option.id} className="question-option">
                      <input
                        type={
                          form.input_type === "single_choice"
                            ? "radio"
                            : "checkbox"
                        }
                        name={key}
                        checked={
                          option.id === "__custom"
                            ? draft.custom
                            : draft.ids.includes(option.id)
                        }
                        onChange={(e) => {
                          if (option.id === "__custom")
                            change(key, {
                              ...draft,
                              custom: e.target.checked,
                              ids:
                                form.input_type === "single_choice"
                                  ? []
                                  : draft.ids,
                            });
                          else if (form.input_type === "single_choice")
                            change(key, {
                              ...draft,
                              custom: false,
                              ids: [option.id],
                            });
                          else
                            change(key, {
                              ...draft,
                              ids: e.target.checked
                                ? [
                                    ...draft.ids.filter(
                                      (id) => id !== option.id,
                                    ),
                                    option.id,
                                  ]
                                : draft.ids.filter((id) => id !== option.id),
                            });
                        }}
                      />
                      {option.label}
                    </label>
                  ),
                )}
              {(!form || form.input_type === "text" || draft.custom) && (
                <InputGroup><InputGroupTextarea
                  aria-label={`${form?.question || q.label}${form ? " · 직접 입력" : ""}`}
                  aria-describedby={
                    context ? `question-context-${q.id}` : undefined
                  }
                  rows={3}
                  maxLength={20000}
                  value={draft.text}
                  onChange={(e) =>
                    change(key, { ...draft, text: e.target.value })
                  }
                /></InputGroup>
              )}
            </fieldset>
          );
        })}
        <ServiceStatusNotice inline />
        <Notice>{error}</Notice>
        <Button
          className="primary"
          disabled={disabled}
          onClick={() => void submit().catch(() => {})}
        >
          답변 제출
        </Button>
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
    (!job.state || job.state.status === "PASS_PENDING_USER_APPROVAL");
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
      {approval && <ChangeReview review={job.change_review} onQuestion={question => {
        const value = feedback.trim() ? `${feedback.trim()}\n\n${question}` : question;
        setFeedback(value); sessionStorage.setItem(prefix + "feedback", value);
        document.getElementById(`feedback-${job.id}`)?.focus();
      }} />}
      <label htmlFor={`feedback-${job.id}`}>{job.can_continue ? "추가 요청 내용" : "수정 의견 보내기"}</label>
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
      <Notice>{error}</Notice>
      {approval && (
        <Item variant="outline" size="sm" className="spec-confirmation">
          <SealCheckIcon weight="duotone" size={25} aria-hidden />
          <ItemContent><ItemTitle>이 명세를 최종 승인할까요?</ItemTitle><ItemDescription>현재 검토본을 확인한 뒤 승인해주세요. 과거 명세를 여는 것만으로 승인되지는 않습니다.</ItemDescription></ItemContent>
          <ItemActions>
            {onReview && <Button onClick={onReview}>현재 검토본 열기</Button>}
            <Button className="primary" disabled={disabled} onClick={() => void perform("approve", null).catch(() => {})}>{approvedExecution === executionKey ? "승인 전송됨" : "이 명세 승인"}</Button>
          </ItemActions>
        </Item>
      )}
    </section>
  );
}
