import type { Job } from "../../shared/types";

export interface ProgressState { job: Job; revision: number; serverOffset: number }
export interface ProgressEvent { event: "job.snapshot" | "job.progress"; job_id: string; revision: number; server_time: string; job: Job }

export function applyProgress(previous: ProgressState | undefined, event: ProgressEvent): { state?: ProgressState; resync: boolean } {
  if (previous && previous.job.id === event.job_id && event.revision <= previous.revision) return { state: previous, resync: false };
  if (event.event === "job.progress" && (!previous || event.revision !== previous.revision + 1)) return { state: previous, resync: true };
  const active = ["queued", "running"].includes(event.job.status);
  const job = event.event === "job.snapshot" ? event.job : { ...previous?.job, ...event.job,
    ...(active ? { state: { ...previous?.job.state, status: event.job.status, allowed_actions: [] } } : {}) };
  const server = Date.parse(event.server_time);
  return { state: { job: { ...job, server_time: event.server_time }, revision: event.revision, serverOffset: Number.isFinite(server) ? server - Date.now() : 0 }, resync: false };
}
