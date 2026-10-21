import type { ChangeReviewData, SpecChange } from "./types";
import { Button } from "./UI";
import "./change-review.css";

const kinds = { added: "추가", removed: "삭제", modified: "변경", moved: "이동" };
const reasons: Record<string, string> = {
  budget_exceeded: "분석 예산을 넘어 의미를 분석하지 못했습니다.",
  context_limit: "필요한 문맥이 입력 한도를 넘어 판단을 보류했습니다.",
  interrupted: "호출이 중단되어 결과를 확인할 수 없습니다.",
  analysis_failed: "분석 결과를 확인하지 못했습니다.",
};

function ChangeItem({ item, review }: { item: SpecChange; review: ChangeReviewData }) {
  return <li><details className="change-item">
    <summary><span className="change-kind">{kinds[item.change]}</span> {item.summary || `${(item.after || item.before)?.section || "명세"} · 의미 미분석`}</summary>
    {item.rationale && <p>{item.rationale}</p>}
    {item.meaning === "uncertain" && <p>문맥이 부족하여 의미 판정을 보류했습니다.</p>}
    {item.status === "unanalysed" && <p>{reasons[item.reason] || "아직 의미를 분석하지 못했습니다."}</p>}
    <div className="change-originals">{([ ["이전", item.before], ["현재", item.after] ] as const).map(([label, location]) =>
      <div key={label}><h5>{label}</h5>{location ? <><p className="subtle">{location.section} · {location.line}행</p><pre>{location.text}</pre></> : <p>해당 본문 없음</p>}</div>)}
    </div>
    {!!item.evidence?.length && <div><h5>사용자 입력 근거</h5>{item.evidence.map((ref, index) => {
      const source = review.sources.find(value => value.source_id === ref.source_id);
      return <div key={index}><blockquote>{ref.quote}</blockquote>{source?.question && <p>질문: {source.question}</p>}
        <details><summary>사용자 원문 전체</summary><pre>{source?.text || "근거 원문 확인 불가"}</pre></details></div>;
    })}</div>}
    {item.diff && <details><summary>줄 단위 비교</summary><pre>{item.diff}</pre></details>}
  </details></li>;
}

export function ChangeReview({ review, onQuestion }: { review?: ChangeReviewData; onQuestion?: (question: string) => void }) {
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
        <p role="status">본문 변경 {review.changes.length}건 중 {review.analysed}건 분석 · {review.remaining === null ? "남은 범위 확인 불가" : `${review.remaining}건 미분석`}</p>}
      {["failed", "partial", "running"].includes(review.status) && <p className="change-warning">일부 또는 전체 변경 분석을 완료하지 못했습니다. 원문을 확인한 후 승인할 수 있습니다.</p>}
      {review.legacy && <p className="subtle">일부 후보에 전체 블록 자료가 없어 원문 섹션으로 비교했습니다.</p>}
      {requested.length > 0 && <section><h4>요청 반영</h4><ul>{requested.map(item => <ChangeItem key={item.id} item={item} review={review} />)}</ul></section>}
      {other.length > 0 && <section><h4>함께 달라진 내용</h4><ul>{other.map(item => <ChangeItem key={item.id} item={item} review={review} />)}</ul></section>}
      {questions.length > 0 && <section><h4>확인할 사항</h4><ul>{questions.map(item => <li key={item.id}><p>{item.question}</p>
        {onQuestion && <Button onClick={() => onQuestion(item.question!)}>수정 의견에 추가</Button>}</li>)}</ul><p className="subtle">확인 질문은 제안이며, 원문을 검토한 후 승인할 수 있습니다.</p></section>}
      {wording.length > 0 && <details><summary>표현만 달라진 내용 {wording.length}건</summary><ul>{wording.map(item => <ChangeItem key={item.id} item={item} review={review} />)}</ul></details>}
    </>}
  </section>;
}
