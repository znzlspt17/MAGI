import { useState } from "react";
import { CaretDownIcon } from "@phosphor-icons/react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "./components/ui/collapsible";
import { Button, formatTime, statusLabel } from "./UI";
import type { Job, Step } from "./types";

const actions: Record<string, string> = { generate: "최초 요청", answer: "질문에 답변", revise: "수정 요청", approve: "명세 승인", retry: "다시 시도" };
const meaningful = (text?: string) => text && !["단계를 완료했습니다.", "사용자 작업을 접수했습니다."].includes(text) ? text : "상세 결과 기록 없음";

export function ExecutionTimeline({ job, nodes, selected, select }: { job: Job; nodes: Step[]; selected: string; select: (id: string) => void }) {
  const events = job.session_events || [];
  const ids = [...new Set([...events.map(e => e.id), ...nodes.map(n => n.execution_id || "legacy")])];
  const initial = nodes.find(n => n.status === "running")?.execution_id || ids.at(-1);
  const [open, setOpen] = useState<Record<string, boolean>>(initial ? { [initial]: true } : {});
  return <ol className="execution-timeline" aria-label="실행별 처리 이력">{ids.map((id, index) => {
    const event = events.find(e => e.id === id);
    const steps = nodes.filter(n => (n.execution_id || "legacy") === id);
    const questions = [...new Set(event?.questions || [])];
    const title = actions[event?.action || steps[0]?.action || ""] || "처리 기록";
    return <li key={id}><Collapsible open={!!open[id]} onOpenChange={value => setOpen(previous => ({ ...previous, [id]: value }))}>
      <CollapsibleTrigger className="execution-run-trigger"><span>{index + 1}. {title}</span><span>{statusLabel(event?.status || steps.at(-1)?.status)}</span><CaretDownIcon aria-hidden size={16} /></CollapsibleTrigger>
      <p className="execution-run-time">{event?.started_at ? `${formatTime(event.started_at)} (KST)` : "시각 기록 없음"}</p>
      <p className="execution-run-summary">{meaningful(event?.summary || steps.at(-1)?.summary)}</p>
      <CollapsibleContent>
        <section className="execution-input"><h3>사용자 입력</h3>
          {event?.input?.request && <p>{event.input.request}</p>}{event?.input?.feedback && <p>{event.input.feedback}</p>}
          {event?.input?.answers?.map((answer, i) => <div className="execution-answer" key={i}><h4>질문</h4><p>{answer.question || "질문 원문 기록 없음"}</p><h4>답변</h4><p>{answer.answer || "답변 기록 없음"}</p>{answer.question_id && <details><summary>질문 참조</summary><code>{answer.question_id}</code></details>}</div>)}
          {event?.action === "approve" && <p>사용자가 명세를 승인했습니다.</p>}
          {event?.action === "retry" && <p>이전에 저장된 입력과 처리 결과를 이어서 사용합니다.</p>}
          {!event?.input?.request && !event?.input?.feedback && !event?.input?.answers?.length && !["approve", "retry"].includes(event?.action || "") && <p>저장된 사용자 입력이 없습니다.</p>}
        </section>
        {!!questions.length && <section><h3>요구사항 확인 {steps.some(n => n.status === "waiting") ? "· 답변 대기" : ""}</h3><ol>{questions.map((q, i) => <li key={i}>{q.replace(/^\[[^\]]+\]\s*/, "")}</li>)}</ol></section>}
        <Collapsible className="execution-steps"><CollapsibleTrigger className="execution-detail-trigger">하위 처리 단계 {steps.length}개<CaretDownIcon size={14} aria-hidden /></CollapsibleTrigger><CollapsibleContent>
          <div className="execution-step-list" role="group" aria-label="실행 흐름">{steps.map(node => <Button key={node.id} aria-pressed={selected === node.id} onClick={() => select(node.id)}>{node.title || node.stage || "처리 단계"} · {statusLabel(node.status)}</Button>)}</div>
        </CollapsibleContent></Collapsible>
      </CollapsibleContent>
    </Collapsible></li>;
  })}</ol>;
}

export function ResearchResult({ research }: { research?: import("./types").ResearchRecord }) {
  if (!research) return <p>당시 조사 상세가 저장되지 않았습니다.</p>;
  const reasons: Record<string, string> = { disabled: "외부 검색이 꺼져 있습니다.", not_required: "자동 검색 조건에 해당하지 않았습니다.", search_failed: "외부 검색 요청에 실패했습니다.", search_results: "검색 결과 링크를 수집했습니다." };
  const outcomes = { skipped: "외부 검색 생략", failed: "외부 검색 실패", no_results: "검색 결과 링크 없음", links_found: `검색 결과 링크 ${research.result_count}개 발견` };
  return <section className="research-result"><h3>검색 수행 기록</h3><strong>{outcomes[research.outcome]}</strong><p>{reasons[research.reason] || "상세 사유 기록 없음"}</p><dl>{research.search_method === "duckduckgo_html_links" && <><dt>검색 방식</dt><dd>DuckDuckGo HTML 검색 결과 링크 수집</dd></>}<dt>검색 모드</dt><dd>{research.mode}</dd><dt>검색 수행</dt><dd>{research.performed ? "시도함" : "생략"}</dd><dt>결과 수</dt><dd>{research.result_count}</dd><dt>기록 시각 (KST)</dt><dd>{formatTime(research.retrieved_at)}</dd>{research.query && <><dt>검색어</dt><dd>{research.query}</dd></>}</dl>
    <p>검색 결과 링크이며, 원문을 읽고 검토한 근거는 아닙니다.</p>
    <ul>{research.sources.map((source, i) => {
      let url: URL | null = null;
      try { const parsed = new URL(source.url); if (["http:", "https:"].includes(parsed.protocol) && !parsed.username && !parsed.password) url = parsed; } catch { /* 잘못된 URL은 링크로 만들지 않는다. */ }
      return <li key={i}>{url ? <a href={url.href} target="_blank" rel="noopener noreferrer">{source.title || url.hostname}</a> : <span>{source.title || "유효하지 않은 출처 링크"}</span>}</li>;
    })}</ul>
  </section>;
}
