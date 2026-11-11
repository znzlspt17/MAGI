import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { StatusIcon } from "../../shared/ui/StatusIcon";
import { formatTime, statusLabel } from "../../shared/ui/UI";
import type { Job } from "../../shared/types";
import { ClockIcon } from "@phosphor-icons/react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../../shared/ui/tooltip";

export function SessionLink({ job, active, onSelect }: { job: Job; active: boolean; onSelect: () => void }) {
  const viewport = useRef<HTMLSpanElement>(null), text = useRef<HTMLSpanElement>(null);
  const [overflow, setOverflow] = useState(0);
  const title = job.request || "저장된 작업";
  useLayoutEffect(() => {
    const measure = () => setOverflow(Math.max(0, (text.current?.scrollWidth || 0) - (viewport.current?.clientWidth || 0)));
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    if (viewport.current) observer?.observe(viewport.current);
    return () => observer?.disconnect();
  }, [title]);
  const style = { "--session-travel": `${-overflow}px`, "--session-duration": `${overflow / 40}s` } as CSSProperties;
  return <TooltipProvider delayDuration={600}><Tooltip><TooltipTrigger asChild><Link className="session-row" to={`/jobs/${job.id}`} aria-current={active ? "page" : undefined} onClick={onSelect}
    style={style} data-overflow={overflow > 0 || undefined}>
    <StatusIcon status={job.status} /><span className="session-title" ref={viewport}><span ref={text}>{title}</span></span>
  </Link></TooltipTrigger><TooltipContent side="right" className="session-tooltip"><div>{title}</div><div className="magi-meta"><span className="magi-meta-item"><StatusIcon status={job.status} />{statusLabel(job.status)}</span><span className="magi-meta-item"><ClockIcon size={14} aria-hidden />{formatTime(job.updated_at || job.created_at)}</span></div></TooltipContent></Tooltip></TooltipProvider>;
}
