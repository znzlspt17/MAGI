import { array, literal, record, requiredObject, text, number, dictionary } from "../../shared/api/response-contract";
import { decodeJob, decodeJobs } from "./job-response";
import { decodeServiceStatus } from "../auth/account-response";

const deleted = requiredObject({ event: literal("records.deleted"), ids: array(text) });
const status = requiredObject({ event: literal("service.status"), status: decodeServiceStatus });
const signal = requiredObject({ event: literal("ready", "job.changed", "server_error") });
export function decodeEvent(value: unknown) {
  const source = record(value);
  switch (source.event) {
    case "session.expired": return { event: "session.expired" } as const;
    case "jobs.snapshot": return { event: "jobs.snapshot", jobs: decodeJobs(source.jobs), revisions: dictionary(number)(source.revisions) } as const;
    case "job.snapshot": case "job.progress": {
      const revision = number(source.revision);
      if (!Number.isSafeInteger(revision) || revision < 1) throw new Error("실행 순번이 올바르지 않습니다.");
      const job = decodeJob(source.job), job_id = text(source.job_id);
      if (job.id !== job_id) throw new Error("작업 식별값이 일치하지 않습니다.");
      return { event: source.event, job_id, revision, server_time: text(source.server_time), job } as const;
    }
    case "jobs.changed": return { event: "jobs.changed", job_id: text(source.job_id), revision: number(source.revision), job: decodeJob(source.job) } as const;
    case "job.subscription_error": return { event: "job.subscription_error" } as const;
    case "records.deleted": return deleted(source);
    case "service.status": return status(source);
    case "ready": case "job.changed": case "server_error": return signal(source);
    default: return { event: "unknown" } as const;
  }
}
