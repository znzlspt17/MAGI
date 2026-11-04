import type { RubricReview as Review } from "../../shared/types";

export function RubricReview({ review }: { review?: Review }) {
  if (!review) return null;
  const stop = { max_score: "10점 도달", patience: "연속 비개선 한도 도달", round_budget: "평가 라운드 소진", "": "평가 진행 중" }[review.termination];
  return <section aria-label="명세 루브릭 평가">
    <h3>명세 평가 {review.score}/10</h3>
    <p>{review.score_reason}</p>
    <p>{stop} · 평가 {review.round}회 · 최고점 후보: {review.selected_cycle}구간 {review.selected_round}회차</p>
    {!!review.remaining_issues.length && <div><h4>남은 결함</h4><ul>{review.remaining_issues.map(issue => <li key={issue.issue_id}>
      [{issue.severity}] {issue.problem} — {issue.required_change}</li>)}</ul></div>}
    {!!review.revision_directives.length && <div><h4>수정 지시</h4><ul>{review.revision_directives.map((text, index) => <li key={index}>{text}</li>)}</ul></div>}
    <details><summary>적용된 루브릭 {review.items.length}개 보기</summary>{review.items.map(item => <article key={item.rubric_id}>
      <h4>{item.rubric_id} · {item.verdict}</h4><p>{item.condition}</p><p>요구사항 {item.requirement_id} · {item.importance}</p>
      {item.basis.map((basis, index) => <blockquote key={index}>{basis.reference}: {basis.quote}</blockquote>)}
      <p>{item.reason}</p><blockquote>{item.section}: {item.evidence_kind === "absence" ? "해당 조건의 근거 없음" : item.quote}</blockquote>
    </article>)}</details>
  </section>;
}
