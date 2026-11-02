import { useEffect, useState } from "react";
import { CheckCircleIcon, CircleNotchIcon, ClockIcon, WarningCircleIcon } from "@phosphor-icons/react";
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

const icon = (status?: string) => status === "running" ? CircleNotchIcon : ["completed", "FINALIZED"].includes(status || "") ? CheckCircleIcon : ["error", "failed", "interrupted", "blocked"].includes(status || "") ? WarningCircleIcon : ClockIcon;

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
  const start = job.status === "queued" ? job.queued_at : current?.started_at || nodes.find(node => node.started_at)?.started_at;
  const Icon = icon(job.status);
  const clock = now + offset;
  const duration = elapsedLabel(start, active ? undefined : job.updated_at, clock);
  return <Trace className="execution-monitor"><TraceCollapsible defaultOpen={false}>
    <TraceCollapsibleTrigger aria-label={`${title}${running.length > 1 ? ` 외 ${running.length - 1}개` : ""} · ${duration}`}><TraceLine status={job.status === "running" ? "running" : undefined}>
      <TraceIcon><Icon className={job.status === "running" ? "execution-monitor-spin" : ""} size={18} /></TraceIcon>
      <TraceTitle><span role="status">{title}{running.length > 1 ? ` 외 ${running.length - 1}개` : ""}</span></TraceTitle>
      <span className="execution-monitor-time" aria-label={`경과 시간 ${duration}`}>{duration}</span>
    </TraceLine></TraceCollapsibleTrigger>
    <TraceCollapsibleContent>
      <ol className="execution-monitor-steps" aria-label="현재 실행 단계">{nodes.map(node => {
        const status = !active && node.status === "running" ? job.status : node.status;
        const NodeIcon = icon(status);
        return <li key={node.id} data-status={status}><button type="button" onClick={() => select(node.id)}>
          <NodeIcon size={17} aria-hidden /><span>{stageLabel(node)}</span><span className="execution-monitor-step-status">{statusLabel(status)}</span>
          <span className="execution-monitor-time">{elapsedLabel(node.started_at, node.completed_at || (active ? undefined : job.updated_at), clock)}</span>
        </button></li>;
      })}</ol>
      {!nodes.length && <p>{job.status === "queued" ? "실행 가능한 순서를 기다리고 있습니다." : "단계 기록을 준비하고 있습니다."}</p>}
      {!active && job.message && <p>{job.message}</p>}
    </TraceCollapsibleContent>
  </TraceCollapsible></Trace>;
}
