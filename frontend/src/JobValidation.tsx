import { useEffect, useState } from "react";
import { api } from "./api";
import { Button } from "./components/ui/button";
import { jobTime } from "./job-data";
import "./job-validation.css";

export type ValidationRecord = {
  record_id: string; created_at: string | null; execution_id: string | null;
  execution_link: "confirmed" | "unconfirmed"; state: "recognized" | "unrecognized" | "unreadable";
  stage: string; error_code: string | null; failed_checks: string[]; attempt: number | null;
  validation_field?: string | null; validation_reason: string | null; validation_section: string | null; validation_index: number | null;
};
type Page = { items: ValidationRecord[]; offset: number; limit: number; next_offset: number | null };
const reasons: Record<string, string> = {
  empty_section: "섹션에 내용 블록이 없습니다", invalid_item_id: "블록 ID가 비어 있거나 중복·예약 ID입니다",
  empty_item_id: "블록 ID가 비어 있습니다", duplicate_item_id: "블록 ID가 중복됐습니다", reserved_item_id: "예약된 LOCKED- 접두사를 사용했습니다",
  empty_text: "블록 본문이 비어 있습니다", unknown_requirement: "알 수 없는 요구사항을 참조했습니다",
  unknown_decision: "알 수 없는 결정을 참조했습니다", unknown_reference: "알 수 없는 요구사항 또는 결정을 참조했습니다",
  fixed_heading: "앱이 조립하는 고정 제목이 본문에 중복됐습니다",
};
const sections: Record<string, string> = {
  mission: "목표", background: "배경", user_intent: "사용자 의도", in_scope: "포함 범위", out_of_scope: "비범위",
  definitions: "용어 정의", evidence_summary: "근거 요약", recommended_requirements: "권장 요구사항", optional_requirements: "선택 요구사항",
  forbidden_behaviors: "금지 동작", input_contract: "입력 계약", output_contract: "출력 계약", architecture: "아키텍처",
  module_responsibilities: "모듈 책임", data_flow: "데이터 흐름", error_handling_policy: "오류 처리", configuration_policy: "설정 정책",
  persistence_artifact_policy: "저장 정책", implementation_order: "구현 순서", acceptance_criteria: "완료 기준",
  test_plan: "테스트 계획", manual_verification_checklist: "수동 검증", instructions_for_ai_coding_agent: "구현 에이전트 지침",
};

export default function JobValidation({ jobId }: { jobId: string }) {
  const [offset, setOffset] = useState(0), [epoch, setEpoch] = useState(0);
  const [page, setPage] = useState<Page | null>(null), [loading, setLoading] = useState(true);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  async function copy(record: ValidationRecord) {
    try { await navigator.clipboard.writeText(JSON.stringify(record, null, 2)); setNotice("진단 요약을 복사했습니다."); }
    catch { setNotice("진단 요약을 복사하지 못했습니다."); }
  }
  useEffect(() => {
    const abort = new AbortController(); setPage(null); setLoading(true); setError(""); setNotice("");
    api<Page>(`/api/admin/job/validation?id=${encodeURIComponent(jobId)}&limit=20&offset=${offset}`, { signal: abort.signal })
      .then(value => { if (!abort.signal.aborted) setPage(value); })
      .catch(e => { if (!abort.signal.aborted) setError(e instanceof Error ? e.message : "진단 기록을 조회하지 못했습니다."); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [jobId, offset, epoch]);
  return <section className="job-validation" aria-label="명세 검증 진단" aria-busy={loading}>
    <div className="job-validation-heading"><h3>명세 검증 기록</h3><Button variant="outline" disabled={loading} onClick={() => { setOffset(0); setEpoch(value => value + 1); }}>진단 다시 조회</Button></div>
    <p className="jobs-muted">저장된 과거 실패 기록입니다. 현재 작업 상태와 다를 수 있으며, 실행 연결이 확인된 기록만 실행 ID를 표시합니다.</p>
    {loading && <p role="status">진단 기록을 불러오는 중…</p>}
    {error && <p role="alert">{error}</p>}
    {page?.items.length === 0 && <p className="jobs-empty">저장된 명세 검증 기록이 없습니다.</p>}
    <ol className="job-validation-records">{page?.items.map(record => {
      const linked = record.execution_link === "confirmed" && !!record.execution_id;
      const params = new URLSearchParams({ job_id: jobId, period: "10080" });
      if (linked) params.set("execution_id", record.execution_id!);
      return <li key={record.record_id}>
        <header><strong>{reasons[record.validation_reason || ""] || "상세 진단 없음"}</strong><time dateTime={record.created_at || undefined}>{jobTime(record.created_at)}{record.created_at ? " KST" : ""}</time></header>
        {record.state === "unreadable" && <p>저장된 진단 형식을 해석할 수 없습니다. 원문은 표시하지 않습니다.</p>}
        <dl><div><dt>검증 코드</dt><dd>{record.error_code || "판별 불가"}</dd></div>
          <div><dt>검증 항목</dt><dd>{record.failed_checks.join(", ") || "판별 불가"}</dd></div>
          <div><dt>섹션</dt><dd>{sections[record.validation_section || ""] || "확인되지 않음"}</dd></div>
          <div><dt>필드</dt><dd>{({ item_id: "블록 ID (item_id)", text: "본문 (text)", requirement_ids: "요구사항 참조 (requirement_ids)", decision_ids: "결정 참조 (decision_ids)" } as Record<string, string>)[record.validation_field || ""] || "확인되지 않음"}</dd></div>
          {record.validation_reason !== "empty_section" && <div><dt>블록 위치</dt><dd>{record.validation_index == null ? "해당 없음 또는 확인되지 않음" : `${record.validation_index + 1}번째 블록`}</dd></div>}
          <div><dt>시도 횟수</dt><dd>{record.attempt == null ? "확인되지 않음" : `${record.attempt} / 4`}</dd></div>
          <div><dt>실행 연결</dt><dd>{linked ? <code>{record.execution_id}</code> : "실행 연결 미확인"}</dd></div>
        </dl>
        <div className="job-validation-actions"><Button variant="outline" onClick={() => void copy(record)}>진단 요약 복사</Button><a href={"/admin/logs?" + params}>관련 로그 보기</a></div>
      </li>;
    })}</ol>
    {page && <div className="jobs-pagination"><span>{page.items.length ? `${page.offset + 1}–${page.offset + page.items.length}번째 기록` : "0개 기록"}</span><div>
      <Button variant="outline" disabled={loading || offset === 0} onClick={() => setOffset(value => Math.max(0, value - 20))}>이전 진단</Button>
      <Button variant="outline" disabled={loading || page.next_offset == null} onClick={() => setOffset(page.next_offset!)}>다음 진단</Button>
    </div></div>}
    <p role="status">{notice}</p><p className="jobs-muted">관련 로그는 최근 7일 보관 범위에서 조회합니다. 이전 진단에 대응하는 로그는 남아 있지 않을 수 있습니다.</p>
  </section>;
}
