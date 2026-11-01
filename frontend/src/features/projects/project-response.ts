import { array, boolean, literal, nullable, number, optional, requiredObject, text } from "../../shared/api/response-contract";

const decision = requiredObject({ id: text, version: number, active: boolean, text, conditions: text, actor: literal("user", "llm"),
  decision_id: text, job_id: text, project_id: text, completed_id: text, source_hash: text,
  source_available: optional(boolean), stale: optional(boolean),
  evidence: array(requiredObject({ item_id: text, section: text, quote: text })) });
export const decodeDecisions = requiredObject({ rows: array(decision), total: number, next_offset: nullable(number), project_id: text });
