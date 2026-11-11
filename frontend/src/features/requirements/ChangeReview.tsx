import type { ChangeReviewData, SpecChange } from "../../shared/types";
import { Button } from "../../shared/ui/UI";
import "./change-review.css";
import "../conversation/question-guidance.css";
import { useId, useState } from "react";
import { ExpandableTextarea } from "../../shared/ui/PromptInput";
import { Field, FieldSet, FieldLegend, FieldLabel, FieldDescription } from "../../shared/ui/field";
import { Badge } from "../../shared/ui/badge";

function ProposalQuestion({ item, disabled, onQuestion }: {
  item: SpecChange; disabled: boolean; onQuestion: (answer: string) => boolean | void;
}) {
  const id = useId();
  const form = item.question_form;
  const [selected, setSelected] = useState<string[]>([]);
  const [custom, setCustom] = useState(false);
  const [answer, setAnswer] = useState("");
  const [detail, setDetail] = useState("");
  const [added, setAdded] = useState(false);
  const [error, setError] = useState("");
  const textOnly = !form || form.input_type === "text";
  const labels = form?.options.filter(option => selected.includes(option.id)).map(option => option.label) || [];
  const response = textOnly ? answer.trim() : custom && !answer.trim() ? "" : [...labels, ...(custom ? [answer.trim()] : [])].join(" / ");
  function append() {
    if (disabled || !response) return;
    const value = `확인 제안: ${item.question}\n답변: ${response}${detail.trim() ? `\n추가 설명: ${detail.trim()}` : ""}`;
    const success = onQuestion(value) !== false;
    setAdded(success);
    setError(success ? "" : "수정 의견 초안에 추가하지 못했습니다. 입력란의 내용을 확인해주세요.");
  }
  return <FieldSet className="change-question question-form" disabled={disabled} onChange={() => { setAdded(false); setError(""); }}>
    <FieldLegend>{item.question}</FieldLegend>
    {!textOnly && <div className="choice-options">{form.options.map(option => <Field key={option.id} className="question-choice-field">
      <FieldLabel className="choice-card" data-selected={selected.includes(option.id)}><input type={form.input_type === "single_choice" ? "radio" : "checkbox"}
        name={id} checked={selected.includes(option.id)} onChange={event => {
          if (form.input_type === "single_choice") setCustom(false);
          setSelected(form.input_type === "single_choice" ? [option.id] : event.target.checked ? [...selected, option.id] : selected.filter(value => value !== option.id));
        }} />
        <span className="choice-copy"><span className="choice-heading">{option.label}{form.recommendation?.option_ids.includes(option.id) && <Badge variant="outline">추천</Badge>}</span>
          {option.impact && <FieldDescription>{option.impact}</FieldDescription>}
          {option.assumptions?.map((assumption, index) => <span className="choice-assumption" key={index}>전제: {assumption}</span>)}
        </span>
      </FieldLabel>
    </Field>)}<Field className="question-choice-field"><FieldLabel className="choice-card" data-selected={custom}><input type={form.input_type === "single_choice" ? "radio" : "checkbox"}
      name={id} checked={custom} onChange={event => { setCustom(event.target.checked); if (form.input_type === "single_choice") setSelected([]); }} />직접 입력</FieldLabel></Field></div>}
    {form?.recommendation && <div className="question-recommendation"><p>모델이 안내한 추천 이유: {form.recommendation.reason}</p>
      {form.recommendation.assumptions.map((assumption, index) => <p key={index}>추천 전제: {assumption}</p>)}</div>}
    {(textOnly || custom) && <Field><FieldLabel htmlFor={`${id}-answer`}>답변 직접 입력</FieldLabel>
      <ExpandableTextarea id={`${id}-answer`} label={`${item.question} 직접 입력`} value={answer} disabled={disabled}
        onChange={event => setAnswer(event.target.value)} /></Field>}
    <Field><FieldLabel htmlFor={`${id}-detail`}>추가 설명 (선택)</FieldLabel>
      <ExpandableTextarea id={`${id}-detail`} label={`${item.question} 추가 설명 (선택)`} value={detail} disabled={disabled}
        onChange={event => setDetail(event.target.value)} /></Field>
    <Button disabled={disabled || !response} onClick={append}>답변을 수정 의견에 추가</Button>
    {added && <p role="status">수정 의견 초안에 추가했습니다. 내용을 확인한 뒤 전송하세요.</p>}
    {error && <p role="alert">{error}</p>}
  </FieldSet>;
}

const kinds = { added: "추가", removed: "삭제", modified: "변경", moved: "이동" };
const reasons: Record<string, string> = {
  budget_exceeded: "분석 예산을 넘어 의미를 분석하지 못했습니다.",
  context_limit: "필요한 문맥이 입력 한도를 넘어 판단을 보류했습니다.",
  interrupted: "호출이 중단되어 결과를 확인할 수 없습니다.",
  analysis_failed: "분석 결과를 확인하지 못했습니다.",
};

function ChangeItem({ item, review }: { item: SpecChange; review: ChangeReviewData }) {
  return <li><details className="change-item">
    <summary><span className="change-kind">{kinds[item.change]}</span> {item.summary || `${(item.after || item.before)?.section || "명세"} 의미 미분석`}</summary>
    {item.rationale && <p>{item.rationale}</p>}
    {item.meaning === "uncertain" && <p>문맥이 부족하여 의미 판정을 보류했습니다.</p>}
    {item.status === "unanalysed" && <p>{reasons[item.reason] || "아직 의미를 분석하지 못했습니다."}</p>}
    <div className="change-originals">{([ ["이전", item.before], ["현재", item.after] ] as const).map(([label, location]) =>
      <div key={label}><h5>{label}</h5>{location ? <><div className="subtle magi-meta"><span>{location.section}</span><span>{location.line}행</span></div><pre>{location.text}</pre></> : <p>해당 본문 없음</p>}</div>)}
    </div>
    {!!item.evidence?.length && <div><h5>사용자 입력 근거</h5>{item.evidence.map((ref, index) => {
      const source = review.sources.find(value => value.source_id === ref.source_id);
      return <div key={index}><blockquote>{ref.quote}</blockquote>{source?.question && <p>질문: {source.question}</p>}
        <details><summary>사용자 원문 전체</summary><pre>{source?.text || "근거 원문 확인 불가"}</pre></details></div>;
    })}</div>}
    {item.diff && <details><summary>줄 단위 비교</summary><pre>{item.diff}</pre></details>}
  </details></li>;
}

export function ChangeReview({ review, onQuestion, disabled = false }: { review?: ChangeReviewData; onQuestion?: (answer: string) => boolean | void; disabled?: boolean }) {
  if (!review) return null;
  const wording = review.changes.filter(item => item.meaning === "wording");
  const meaningful = review.changes.filter(item => item.meaning !== "wording");
  const requested = meaningful.filter(item => item.status === "analysed" && item.relation === "direct");
  const other = meaningful.filter(item => !requested.includes(item));
  const questions = review.changes.filter(item => item.question);
  return <section className="change-review" aria-label="승인 전 명세 변경 검토">
    <h3>이전 검토본에서 달라진 내용</h3>
    {review.status === "no_baseline" ? <p>첫 승인 후보입니다. 비교할 이전 검토본이 없습니다.</p> : <>
      {review.remaining === null ? <p role="status">변경 범위를 확인하지 못했습니다.</p> : review.status === "unchanged" ? <p>비교 가능한 본문 변경이 없습니다. 의미의 안전성을 보증하는 결과는 아닙니다.</p> :
        <div className="magi-meta" role="status"><span>본문 변경 {review.changes.length}건 중 {review.analysed}건 분석</span><span>{review.remaining === null ? "남은 범위 확인 불가" : `${review.remaining}건 미분석`}</span></div>}
      {["failed", "partial", "running"].includes(review.status) && <p className="change-warning">일부 또는 전체 변경 분석을 완료하지 못했습니다. 원문을 확인한 후 승인할 수 있습니다.</p>}
      {requested.length > 0 && <section><h4>요청 반영</h4><ul>{requested.map(item => <ChangeItem key={item.id} item={item} review={review} />)}</ul></section>}
      {other.length > 0 && <section><h4>함께 달라진 내용</h4><ul>{other.map(item => <ChangeItem key={item.id} item={item} review={review} />)}</ul></section>}
      {questions.length > 0 && <section><h4>확인할 사항</h4><ul className="change-questions">{questions.map(item => <li key={`${review.after_hash}:${item.id}:${item.question_form?.form_version || item.question}`}>
        {onQuestion ? <ProposalQuestion item={item} disabled={disabled} onQuestion={onQuestion} /> : <p>{item.question}</p>}
      </li>)}</ul><p className="subtle">확인 질문은 제안이며, 답하지 않아도 원문을 검토한 후 승인할 수 있습니다.</p></section>}
      {wording.length > 0 && <details><summary>표현만 달라진 내용 {wording.length}건</summary><ul>{wording.map(item => <ChangeItem key={item.id} item={item} review={review} />)}</ul></details>}
    </>}
  </section>;
}
