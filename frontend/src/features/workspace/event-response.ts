import { array, literal, record, requiredObject, text } from "../../shared/api/response-contract";
import { decodeServiceStatus } from "../auth/account-response";

const deleted = requiredObject({ event: literal("records.deleted"), ids: array(text) });
const status = requiredObject({ event: literal("service.status"), status: decodeServiceStatus });
const signal = requiredObject({ event: literal("ready", "job.changed", "server_error") });
export function decodeEvent(value: unknown) {
  const source = record(value);
  switch (source.event) {
    case "records.deleted": return deleted(source);
    case "service.status": return status(source);
    case "ready": case "job.changed": case "server_error": return signal(source);
    default: return { event: "unknown" } as const;
  }
}
