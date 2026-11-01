import { array, boolean, number, optional, requiredObject, text } from "../../shared/api/response-contract";

export const decodeDocument = requiredObject({ content: text, completed_id: optional(text), filename: optional(text),
  language: optional(text), source_hash: optional(text), kind: optional(text) });
export const decodePackage = requiredObject({ completed_id: text, bundle_id: text, filename: text, available: boolean,
  completeness: text, korean_included: boolean, task_count: number, total_size: number, source_hash: text,
  files: array(requiredObject({ name: text, size: number, sha256: text })), limitations: array(text) });
