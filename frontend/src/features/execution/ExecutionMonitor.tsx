import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { useEffect, useState } from "react";
import { StatusIcon } from "../../shared/ui/StatusIcon";
import { Trace, TraceCollapsible, TraceCollapsibleTrigger, TraceCollapsibleContent, TraceLine, TraceIcon, TraceTitle } from "../../shared/ui/trace";
import { statusLabel } from "../../shared/ui/UI";
import { stageLabel } from "./step-view";
import type { Job } from "../../shared/types";
import "./execution-monitor.css";

export function elapsedLabel(start?: string, end?: string, now = Date.now()) {
  const began = start ? Date.parse(start) : NaN, stopped = end ? Date.parse(end) : now;
  if (!Number.isFinite(began) || !Number.isFinite(stopped)) return "시작 시각 확인 중";
  const seconds = Math.max(0, Math.floor((stopped - began) / 1000));
  return seconds < 60 ? `${seconds}초` : `${Math.floor(seconds / 60)}분 ${seconds % 60}초`;
}

const intakeStages = new Set(["generate", "answer", "revise", "approve", "message", "continue", "retry"]);
const validTime = (value?: string) => !!value && Number.isFinite(Date.parse(value));

export function ExecutionMonitor({ job, select }: { job: Job; select: (id: string) => void }) {
  const [now, setNow] = useState(Date.now);
  const [offset, setOffset] = useState(0);
  const active = ["queued", "running"].includes(job.status);
  useEffect(() => {
    const server = Date.parse(job.server_time || "");
    setOffset(Number.isFinite(server) ? server - Date.now() : 0);
  }, [job.server_time]);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  const nodes = (job.execution_graph?.nodes || []).filter(node => node.execution_id === job.execution_id);
  const running = active ? nodes.filter(node => node.status === "running") : [];
  const current = running.at(-1);
  const title = job.status === "queued" ? "실행 순서 대기" : current ? `${stageLabel(current)} 중` : job.status === "running" ? "실행 준비 중" : statusLabel(job.status);
  // 2026-11-07: 단계 변경이나 새로고침과 관계없이 이번 실행의 접수부터 시간을 누적한다.
  const start = validTime(job.queued_at) ? job.queued_at : nodes
    .map(node => node.started_at).filter((value): value is string => validTime(value))
    .sort((a, b) => Date.parse(a) - Date.parse(b))[0];
  const clock = now + offset;
  const duration = elapsedLabel(start, active ? undefined : job.updated_at, clock);
  return <Trace className="execution-monitor"><TraceCollapsible defaultOpen={false}>
    <TraceCollapsibleTrigger title={title} aria-label={`${title}${running.length > 1 ? ` 외 ${running.length - 1}개` : ""} 경과 시간 ${duration}`}><TraceLine>
      <TraceIcon><StatusIcon status={job.status} size={18} /></TraceIcon>
      <TraceTitle className="sr-only"><span role="status">{title}{running.length > 1 ? ` 외 ${running.length - 1}개` : ""}</span></TraceTitle>
      <span className="execution-monitor-time" aria-label={`경과 시간 ${duration}`}>{duration}</span>
    </TraceLine></TraceCollapsibleTrigger>
    <TraceCollapsibleContent>
      <ol className="execution-monitor-steps" aria-label="현재 실행 단계">{nodes.map(node => {
        const status = !active && node.status === "running" ? job.status : node.status;
        const end = node.completed_at || (!active && node.status === "running" ? job.updated_at : undefined);
        const stepDuration = end ? elapsedLabel(node.started_at, end, clock)
          : active && node.status === "running" ? elapsedLabel(node.started_at, undefined, clock)
          : "소요 시간 기록 없음";
        return <li key={node.id} data-status={status}><AstryxButton variant="ghost" label={`${stageLabel(node)} ${statusLabel(status)} ${stepDuration}`} onClick={() => select(node.id)}>
          <StatusIcon status={status} size={17} /><span>{stageLabel(node)}</span><span className="execution-monitor-step-status sr-only">{statusLabel(status)}</span>
          {!intakeStages.has(node.stage || "") && <span className="execution-monitor-time">{stepDuration}</span>}
        </AstryxButton></li>;
      })}</ol>
      {!nodes.length && <p>{job.status === "queued" ? "실행 가능한 순서를 기다리고 있습니다." : "단계 기록을 준비하고 있습니다."}</p>}
      {!active && job.message && <p>{job.message}</p>}
    </TraceCollapsibleContent>
  </TraceCollapsible></Trace>;
}
