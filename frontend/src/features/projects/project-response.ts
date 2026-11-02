import { array, boolean, literal, nullable, number, optional, requiredObject, text } from "../../shared/api/response-contract";

const decisionFields = { text, conditions: text, actor: literal("user", "llm"),
  decision_id: text, job_id: text, project_id: text, completed_id: text, source_hash: text,
  source_available: optional(boolean), stale: optional(boolean),
  evidence: array(requiredObject({ item_id: text, section: text, quote: text })) };
const candidate = requiredObject(decisionFields);
const reused = requiredObject({ ...decisionFields, id: text, version: number });
const decision = requiredObject({ ...decisionFields, id: text, version: number, active: boolean });
export const decodeDecisions = requiredObject({ rows: array(decision), total: number, next_offset: nullable(number), project_id: text });
export const decodeDecisionCandidates = requiredObject({ rows: array(candidate), total: number, next_offset: nullable(number), project_id: text });
export const decodeReusedDecisions = requiredObject({ rows: array(reused), total: number, next_offset: nullable(number) });

export type CommonDecision = ReturnType<typeof decision>;
export type DecisionCandidate = ReturnType<typeof candidate>;
export type ReusedDecision = ReturnType<typeof reused>;
export type DecisionSource = Pick<DecisionCandidate, "job_id" | "completed_id" | "source_hash" | "evidence" | "source_available">;
