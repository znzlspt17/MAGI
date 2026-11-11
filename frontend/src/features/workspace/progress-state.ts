import type { Job } from "../../shared/types";

export type WorkspaceStage = "request" | "questions" | "review" | "final";

// 2026-11-09: 표시 단계는 서버 상태의 설명이며 실행 중 이전 상태를 완료로 추측하지 않는다.
export function workspaceStage(job: Job | null): WorkspaceStage | null {
  if (!job) return "request";
  if (["running", "queued"].includes(job.status)) return null;
  const status = ["error", "interrupted"].includes(job.status)
    ? job.retry_status : job.state?.status || job.status;
  if (["NEEDS_USER_INPUT", "waiting"].includes(status || "")) return "questions";
  if (["PASS_PENDING_USER_APPROVAL", "waiting_approval", "CRITICAL_BLOCKED", "blocked", "needs_revision"].includes(status || "")) return "review";
  if (status === "FINALIZED") return "final";
  return null;
}

export function workspaceStageMessage(job: Job | null): string {
  if (job?.status === "running") return "요청을 처리하고 있습니다";
  if (job?.status === "queued") return "실행 순서를 기다리고 있습니다";
  if (job && ["error", "interrupted"].includes(job.status)) return "작업이 중단되었습니다. 아래에서 복구 방법을 확인하세요";
  return job ? "현재 작업 상태를 확인해주세요" : "현재 작업 상태를 확인하고 있습니다";
}

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
