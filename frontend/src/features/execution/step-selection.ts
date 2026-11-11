import type { Job, Step } from "../../shared/types";

// 2026-11-09: 이전 완료본이 현재 승인 후보보다 먼저 선택되지 않도록 실행 문서를 별도로 식별한다.
export function currentDocumentStep(job: Job): string | undefined {
  if (job.status === "FINALIZED" && job.latest_completed?.step_id) return job.latest_completed.step_id;
  const candidates = [...(job.execution_graph?.nodes || [])].reverse().filter(node => node.has_document);
  return (job.execution_id ? candidates.find(node => node.execution_id === job.execution_id) : candidates[0])?.id;
}

export function automaticStep(nodes: Step[], status: string): string {
  const newest = [...nodes].reverse();
  if (status === "error") {
    const failed = newest.find(node => node.status === "failed");
    if (failed) return failed.id;
  }
  if (status === "CRITICAL_BLOCKED") {
    const stopped = newest.find(node => node.status === "blocked");
    if (stopped) return stopped.id;
  }
  return (newest.find(node => node.has_document) || newest[0])?.id || "";
}
