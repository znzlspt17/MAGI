import { array, boolean, number, requiredObject, text } from "../../shared/api/response-contract";

export const decodePackage = requiredObject({ completed_id: text, bundle_id: text, filename: text, available: boolean,
  completeness: text, task_count: number, total_size: number, source_hash: text,
  files: array(requiredObject({ name: text, size: number, sha256: text })), limitations: array(text) });
