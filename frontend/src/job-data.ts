import type { SessionEvent } from "./types";

export type JobRecord = {
  id: string;
  request?: string | null;
  status?: string | null;
  owner_id?: string | null;
  created_at?: string | null;
};
export type JobDetail = JobRecord & {
  final?: string;
  candidate?: string;
  critical?: string;
  session_events?: Partial<SessionEvent>[];
};
export type JobCatalog = { jobs: JobRecord[]; pending: string[] };
export type CleanupOperation = {
  id: string; scope: string; targets?: string[];
  counts: { jobs: number; files?: number; project_decisions?: number };
  external_references?: number; skipped?: unknown[];
};

export function jobTime(value?: string | null) {
  if (!value || Number.isNaN(Date.parse(value))) return "기록 없음";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul", dateStyle: "short", timeStyle: "short", hour12: false,
  }).format(new Date(value));
}

export function filterJobs(jobs: JobRecord[], query: string, owner: string, status: string) {
  const text = query.trim().toLocaleLowerCase("ko-KR");
  return jobs.filter(job =>
    (!owner || (owner === "unowned" ? !job.owner_id : job.owner_id === owner)) &&
    (!status || (job.status || "unknown") === status) &&
    `${job.request || ""} ${job.id} ${job.owner_id || ""}`.toLocaleLowerCase("ko-KR").includes(text),
  ).sort((a, b) => {
    const first = a.created_at ? Date.parse(a.created_at) : NaN;
    const second = b.created_at ? Date.parse(b.created_at) : NaN;
    const aTime = Number.isNaN(first) ? -Infinity : first;
    const bTime = Number.isNaN(second) ? -Infinity : second;
    return (aTime === bTime ? 0 : bTime > aTime ? 1 : -1) || a.id.localeCompare(b.id);
  });
}
