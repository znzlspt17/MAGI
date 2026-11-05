import type { Step } from "../../shared/types";

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
