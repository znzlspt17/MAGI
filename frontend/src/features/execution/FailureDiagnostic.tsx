import type { FailureDiagnosticData } from "./execution-detail";
import type { Job } from "../../shared/types";
import { stageLabel } from "./step-view";

// 2026-11-05: 서버가 검증한 코드만 설명하고 알 수 없는 세부 사유는 추측하지 않는다.
const reasons: Record<string, string> = {
  rubric_input_changed: "현재 요구사항과 검토 기준이 같은 입력을 사용하는지 확인하지 못했습니다.",
  evaluation_missing: "현재 초안에 대한 검토 결과를 찾지 못했습니다.",
  evaluation_draft_mismatch: "검토 결과가 현재 초안을 평가한 것인지 확인하지 못했습니다.",
  stored_evaluation_invalid: "저장된 검토 결과의 근거 또는 연결을 확인하지 못했습니다.",
  rubric_evidence: "검토 근거가 초안의 섹션 또는 인용과 일치하는지 확인하지 못했습니다.",
  quote_not_found: "검토에 사용한 인용을 해당 초안 섹션에서 찾지 못했습니다.",
  section_invalid: "검토한 섹션이 해당 기준에 허용된 영역인지 확인하지 못했습니다.",
  reason_missing: "검토 판정에 필요한 이유를 확인하지 못했습니다.",
  rubric_issue: "검토 판정과 발견한 결함의 연결을 확인하지 못했습니다.",
  issue_link_invalid: "검토 판정과 결함의 연결이 서로 일치하지 않습니다.",
  rubric_evaluation_coverage: "모든 검토 기준이 한 번씩 평가되었는지 확인하지 못했습니다.",
  evaluation_coverage_mismatch: "검토 기준과 평가 항목의 수 또는 연결이 일치하지 않습니다.",
  rubric_score: "검토 점수 또는 수정 제안의 검증에 실패했습니다.",
  score_invalid: "검토 점수 또는 수정 제안의 검증에 실패했습니다.",
  rubric_basis: "검토 기준과 확정 요구사항의 근거 연결을 확인하지 못했습니다.",
  requirement_unknown: "검토 기준이 참조한 요구사항을 확정 목록에서 찾지 못했습니다.",
  condition_missing: "검토 기준의 검사 조건을 확인하지 못했습니다.",
  importance_invalid: "검토 기준의 중요도가 해당 요구사항에 맞는지 확인하지 못했습니다.",
  basis_reference_invalid: "검토 기준의 근거가 해당 요구사항을 참조하는지 확인하지 못했습니다.",
  basis_quote_not_found: "검토 기준의 근거 인용을 확정 요구사항에서 찾지 못했습니다.",
  rubric_coverage_missing: "일부 필수 요구사항 또는 제약의 검토 기준을 찾지 못했습니다.",
  rubric_coverage: "필수 요구사항과 제약이 검토 기준에 모두 포함되었는지 확인하지 못했습니다.",
  rubric_identity: "검토 기준의 식별자가 유일한지 확인하지 못했습니다.",
  rubric_boundary: "검토 기준이 제품 범위와 일치하는지 확인하지 못했습니다.",
  rubric_schema: "검토 기준의 형식을 확인하지 못했습니다.",
  recovery_exhausted: "같은 상태 불일치가 복구 후에도 반복되었습니다.",
};
// 2026-11-05: 분류별 영향과 다음 확인은 함께 변경되는 표시 정책이다.
const categoryPolicy: Record<NonNullable<FailureDiagnosticData["category"]>, { impact: string; nextCheck: string }> = {
  response_invalid: { impact: "검증되지 않은 검토 결과로 명세를 진행하지 않았습니다.", nextCheck: "실행 이력에서 자동 보정 경과와 검증 실패 항목을 확인하세요." },
  prerequisite_stale: { impact: "현재 입력에 맞는 검토를 확인하기 전까지 작업을 중단했습니다.", nextCheck: "실행 이력에서 선행 자료와 복구 경과를 확인하세요." },
  execution_uncertain: { impact: "이전 외부 호출의 완료 여부를 확인하지 못해 자동 반복을 중단했습니다.", nextCheck: "호출 반복에 대한 동의 여부를 확인하세요." },
  persistence_failed: { impact: "처리 결과의 저장 완료 여부를 확인하지 못했습니다.", nextCheck: "실행 이력과 저장 상태를 확인하세요." },
};

function explanation(value: FailureDiagnosticData) {
  return reasons[value.validation_reason || ""] || value.failed_checks?.map(check => reasons[check]).find(Boolean);
}

function Context({ value }: { value: NonNullable<FailureDiagnosticData["context"]> }) {
  return <>{value.rubric_id && <p>검토 기준 참조: {value.rubric_id}</p>}
    {value.requirement_id && <p>요구사항 참조: {value.requirement_id}</p>}
    {!!value.allowed_sections?.length && <p>허용 섹션: {value.allowed_sections.join(", ")}</p>}
    {value.expected_count !== undefined && <p>예상 개수: {value.expected_count}</p>}
    {value.actual_count !== undefined && <p>확인된 개수: {value.actual_count}</p>}</>;
}

type RetryStatus = Pick<Job, "can_retry" | "retry_requires_replay" | "retry_unavailable_reason">;

export function FailureDiagnostic({ value, fallbackStage, recovered = false, retry }: { value?: FailureDiagnosticData; fallbackStage?: string; recovered?: boolean; retry?: RetryStatus }) {
  if (!value) return null;
  const stage = value.error_stage || fallbackStage;
  const reason = explanation(value);
  const policy = value.category ? categoryPolicy[value.category] : undefined;
  // 2026-11-06: 이전 기록이 부분적으로 누락되면 시도 횟수를 추정하지 않는다.
  const attempts = value.attempts;
  const completeAttempts = attempts?.length && attempts.every((entry, index) => entry.attempt === index + 1);
  return <section aria-label={recovered ? "보정 경과" : "실패 진단"} className="failure-diagnostic">
    <h3>{recovered ? "보정 경과" : "실패 진단"}</h3>
    {recovered ? <p>자동 보정 후 단계가 완료되었습니다.</p> : <>
      {stage && <p><strong>실패 단계: </strong>{stageLabel({ id: "", stage })}</p>}
      <p><strong>확인하지 못한 내용: </strong>{reason || "상세 원인이 기록되지 않았거나 확인되지 않았습니다."}</p>
      {value.context && <Context value={value.context} />}
      {completeAttempts && <div className="magi-meta"><strong>처리 경과</strong><span>검증 {attempts.length}회</span><span>자동 보정 {attempts.length - 1}회</span></div>}
      {!completeAttempts && <p><strong>처리 경과: </strong>검증 및 자동 보정 횟수를 확인할 수 없습니다.</p>}
      {policy && <p><strong>영향: </strong>{policy.impact}</p>}
      {retry?.can_retry === true && <p><strong>다시 시도: </strong>{retry.retry_requires_replay ? "호출 반복 가능성 확인 후 다시 시도할 수 있습니다." : "저장된 답변을 유지하고 다시 시도할 수 있습니다."}</p>}
      {retry?.can_retry === false && <p><strong>다시 시도: </strong>{retry.retry_unavailable_reason || "현재 다시 시도할 수 없습니다."}</p>}
      <p><strong>다음 확인: </strong>{policy?.nextCheck || "실행 이력에서 실패 단계와 보정 경과를 확인하세요."}</p>
    </>}
    <details><summary>기술 진단 상세</summary>
      {value.error_code && <p>{value.error_code}</p>}
      {value.error_stage && <p>단계 코드: {value.error_stage}</p>}
      {value.category && <p>실패 분류: {value.category}</p>}
      {value.validation_reason && <p>세부 사유: {value.validation_reason}</p>}
      {!!value.failed_checks?.length && <p>검증 항목: {value.failed_checks.join(", ")}</p>}
      {value.validation_section && <p>섹션: {value.validation_section}</p>}
      {value.validation_field && <p>필드: {value.validation_field}</p>}
      {value.validation_index !== undefined && <p>위치: {value.validation_index}</p>}
      {!!value.attempts?.length && <ol aria-label="보정 시도 이력">{value.attempts.map((attempt, index) => <li key={`${attempt.attempt ?? "unknown"}-${index}`}>
        <div className="magi-meta"><span>{attempt.attempt !== undefined ? `${attempt.attempt}회차` : "시도 횟수 기록 없음"}</span>{attempt.validation_reason && reasons[attempt.validation_reason] && <span>{reasons[attempt.validation_reason]}</span>}</div>
        {attempt.error_code && <p>오류 코드: {attempt.error_code}</p>}
        {attempt.validation_reason && <p>세부 사유: {attempt.validation_reason}</p>}
        {!!attempt.failed_checks?.length && <p>검증 항목: {attempt.failed_checks.join(", ")}</p>}
        {attempt.context && <Context value={attempt.context} />}
      </li>)}</ol>}
    </details>
  </section>;
}
