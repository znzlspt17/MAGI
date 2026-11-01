import type { StopDiagnosticData } from "./execution-detail";

export function StopDiagnostic({ value }: { value?: StopDiagnosticData }) {
  if (!value) return null;
  return <section aria-label="중단 진단">
    <h3>{value.stop_reason === "repair_limit" ? "검토·보완 횟수 소진" : value.stop_reason === "no_progress" ? "동일 결함 반복" : "진행 중단 진단"}</h3>
    <p>{value.cause}</p>
    {value.recording_incomplete && <p>남은 결함 또는 보완 이력 기록이 부족합니다. 저장된 내용만 표시합니다.</p>}
    {!!value.completed_work?.length && <section><h3>수행한 작업 · 작업 전체 누적</h3><ul>
      {value.completed_work.map((work) => <li key={work.action}>{({ spec_compile: "초안 작성·보완", checklist_critic: "명세 검토", review_resolution: "해결 방법 판단" } as Record<string, string>)[work.action || ""]} · {work.count}회 완료</li>)}
    </ul><p>작업 완료 횟수는 개별 수정의 반영이나 결함 해소를 의미하지 않습니다.</p></section>}
    <h3>남은 문제와 해결 방향</h3>
    {(value.issues || []).map((issue, index) => <article className="issue-card" key={issue.issue_id || index}>
      <h4>{issue.problem || "문제 설명 기록 없음"}</h4>
      {issue.requirement_id && <p>관련 요구사항: {issue.requirement_id}</p>}
      {issue.resolution_reason && <p>해결 판단: {issue.resolution_reason}</p>}
      {issue.decision_answer_id && <p>재사용한 답변: {issue.decision_answer_id}</p>}
      {!!issue.basis_refs?.length && <p>확정 근거: {issue.basis_refs.join(", ")}</p>}
      <p><strong>{issue.resolution_kind === "user_decision" ? "사용자 결정 필요" : "시스템 보완 대상"}</strong></p>
      <p>다음 보완: {issue.required_change || "구체적인 수정 방향 기록이 없습니다. 지적 위치와 초안 대조가 필요합니다."}</p>
      {!!issue.attempts?.length && <details open><summary>이전 보완 제안과 재검토 결과</summary>
        {issue.attempts.map((attempt, n) => <section key={n}>
          <h4>검토 {attempt.review_round}</h4><p>제안한 수정: {attempt.proposed_change || "기록 없음"}</p><p>{attempt.outcome}</p>
        </section>)}
      </details>}
    </article>)}
    <p>{value.next_check}</p>
    <p>확정 근거로 보완할 문제는 추가 의견 없이 ‘저장된 결과로 추가 실행’을 선택할 수 있습니다. 사용자 결정이 필요한 문제는 질문의 선택지로 답변해주세요. 추가 실행으로 해결되지 않을 수 있습니다.</p>
  </section>;
}

