import { Notice, statusLabel } from "../../shared/ui/UI";
import { ResearchResult } from "./ExecutionTimeline";
import { questionDetails } from "../conversation/QuestionActions";
import { StopDiagnostic } from "./StopDiagnostic";
import { FailureDiagnostic } from "./FailureDiagnostic";
import { DetailNotices } from "./DetailNotices";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../../shared/ui/collapsible";
import type { Job, Step } from "../../shared/types";
import type { StepDetail } from "./execution-detail";
import "./model-call-summary.css";

import { stageLabel, stepContent, requirementGroups } from "./step-view";
export { stageLabel } from "./step-view";

export function StepResult({ node, detail, hideQuestions = false, retry }: { node?: Step; detail: StepDetail; hideQuestions?: boolean; retry?: Pick<Job, "can_retry" | "retry_requires_replay" | "retry_unavailable_reason"> }) {
  const result = detail.result || {};
  const groups = requirementGroups(result);
  const content = stepContent(node, detail);
  const summary = result.summary || node?.summary || "";
  const genericSummary = !summary || ["단계를 완료했습니다.", "사용자 작업을 접수했습니다."].includes(summary);
  const misleadingFailure = ["failed", "error"].includes(node?.status || detail.status || "") &&
    ["검토 결과를 저장했습니다.", "단계를 완료했습니다.", "재시도를 완료했습니다."].includes(summary);
  return (
    <section className="step-result">
      <span className="eyebrow">{statusLabel(node?.status)}</span>
      <h2>{stageLabel(node)}</h2>
      {content.kind === "plan" && (content.plan ? <section aria-label="저장된 작업 계획">
        <h3>{content.plan.goal}</h3>
        <p><strong>선택한 작업: </strong>{stageLabel({ id: "", stage: content.plan.action })}</p>
        <p><strong>판단 근거: </strong>{content.plan.reason}</p>
        {content.plan.target && <p><strong>작업 대상: </strong>{content.plan.target}</p>}
        {content.plan.expected_result && <p><strong>예상 결과: </strong>{content.plan.expected_result}</p>}
        {!!content.plan.tasks?.length && <ul>{content.plan.tasks.map((task) => <li className="magi-meta" key={task.id}><span>{task.title}</span><span>{({ pending: "예정", completed: "완료", blocked: "대기" } as Record<string, string>)[task.status || ""] || task.status}</span></li>)}</ul>}
        {!!content.plan.input_refs?.length && <p><strong>참조한 근거: </strong>{content.plan.input_refs.join(", ")}</p>}
        {!!content.plan.affected_requirement_ids?.length && <p><strong>관련 요구사항: </strong>{content.plan.affected_requirement_ids.join(", ")}</p>}
      </section> : <p>당시 작업 계획의 상세 내용이 저장되지 않았습니다.</p>)}
      {content.kind === "resolution" && content.action && <p><strong>다음 처리: </strong>{({ repair: "초안 수정·재검토", ask_user: "사용자 결정 확인", stop: "보완 중단", approve: "승인 후보 준비" } as Record<string, string>)[content.action] || content.action}</p>}
      <StopDiagnostic value={result.stop_diagnostic} />
      {result.rubric_summary && <section aria-label="루브릭 검증"><h3>루브릭 검증</h3>
        <div className="magi-meta"><span>검사 기준 {result.rubric_summary.item_count}개</span><span>{result.rubric_summary.status === "ready" ? "생성 완료" : "평가 완료"}</span></div>
        {result.rubric_summary.status === "evaluated" && <div className="magi-meta"><span>충족 {result.rubric_summary.PASS}</span><span>미충족 {result.rubric_summary.FAIL}</span><span>판단 불가 {result.rubric_summary.UNDETERMINED}</span></div>}
      </section>}
      {result.wait_reason && <p><strong>중단·대기 사유: </strong>{result.wait_reason}</p>}
      <FailureDiagnostic value={result.diagnostic} fallbackStage={node?.stage} recovered={(node?.status || detail.status) === "completed"} retry={retry} />
      <DetailNotices detail={detail} />
      <ModelCallSummary calls={detail.model_calls} />
      {content.kind !== "research" && !misleadingFailure && summary !== result.wait_reason && (!genericSummary || !result.diagnostic) && <p>{genericSummary ? "상세 결과 기록 없음" : summary}</p>}
      {content.kind === "research" && <ResearchResult research={content.research} />}
      {result.purpose && <p>{result.purpose}</p>}
      {result.request && <p>{result.request}</p>}
      {result.feedback && <p>{result.feedback}</p>}
      {(result.answers || []).map((answer, i) => (
        <section className="execution-answer" key={i}><h3>질문</h3><p>{answer.question ? questionDetails(answer.question, i).label : "질문 원문 기록 없음"}</p><h3>답변</h3><p>{answer.answer || "답변 기록 없음"}</p>{answer.question_id && <details><summary>질문 참조</summary><code>{answer.question_id}</code></details>}</section>
      ))}
      {!hideQuestions && (result.questions || result.blocking_questions || []).map((q: string, i: number) => <p key={i}>{questionDetails(q, i).label}</p>)}
      {content.kind === "legacy" && <Notice>이전 버전의 단계입니다. 저장된 표시 가능 기록을 제공합니다.</Notice>}
      {groups.map(group => <section key={group.title}>
        <h3>{group.title}</h3>
        <ul>{group.items.map((item, index) => <li key={index}>{item}</li>)}</ul>
      </section>)}

    </section>
  );
}

function ModelCallSummary({ calls }: { calls: StepDetail["model_calls"] }) {
  const token = (value: number | null) => value === null ? "알 수 없음" : value.toLocaleString("ko-KR");
  const status = { attempt: "진행 중", success: "호출 완료", failed: "호출 실패" } as const;
  // 2026-11-07: 모델 응답은 신뢰하지 않고 텍스트로만 표시하며 과거 기록의 부재를 구분한다.
  return <Collapsible className="model-call-summary">
    <CollapsibleTrigger className="model-call-summary-trigger">모델 판단 요약</CollapsibleTrigger>
    <CollapsibleContent>
    {calls === undefined ? <p>모델 호출 기록 없음</p> : calls.length === 0 ? <p>이 단계의 모델 호출이 없습니다.</p> :
      <ol>{calls.map(call => {
        const title = stageLabel({ id: call.id, stage: call.stage });
        return <li key={call.id}>
          <h3 className="magi-meta"><span>{title === "실행 단계" ? call.stage : title}</span><span>{call.attempt}회차</span><span>{status[call.status]}</span></h3>
          <div className="magi-meta"><span>추론 {call.request_settings.reasoning.mode}</span><span>강도 {call.request_settings.reasoning.effort}</span><span>상세도 {call.request_settings.verbosity}</span><span>최대 출력 {token(call.request_settings.max_output_tokens)}</span></div>
          <div className="magi-meta"><span>입력 {token(call.input_tokens)} 토큰</span><span>출력 {token(call.output_tokens)} 토큰</span><span>추론 {token(call.reasoning_tokens)} 토큰</span></div>
          {call.reasoning_summary === null ? <p>요약 미제공</p> : <p className="model-call-summary-text">{call.reasoning_summary}</p>}
          {call.summary_truncated && <p>요약 일부가 생략되었습니다.</p>}
        </li>;
      })}</ol>}
    </CollapsibleContent>
  </Collapsible>;
}
