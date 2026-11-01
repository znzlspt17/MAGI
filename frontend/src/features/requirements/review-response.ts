import { array, boolean, literal, nullable, number, optional, record, requiredObject, text } from "../../shared/api/response-contract";

const evidence = requiredObject({ item_id: text, section: text, quote: text, start: number, end: number, line: number,
  shared: boolean, provenance: text, truncated: optional(boolean), category: optional(text) });
const row = requiredObject({ id: text, text, group: text, spec_status: text, acceptance_status: text,
  verification_status: text, test_status: literal("not_collected"), specification: array(evidence), acceptance: array(evidence),
  verification: array(evidence), specification_total: number, acceptance_total: number, verification_total: number });
const readyReview = requiredObject({ status: literal("ready", "limited"), message: text,
  basis: optional(requiredObject({ id: text, source_hash: text })), review_status: optional(text),
  summary: optional(requiredObject({ total: number, spec_linked: number, acceptance_linked: number, verification_linked: number })),
  rows: array(row), unlinked: array(evidence), unlinked_total: number, evidence: optional(array(evidence)),
  requirement: optional(requiredObject({ text })), total: number, has_more: boolean, offset: number });
const unavailableReview = requiredObject({ status: literal("unavailable"), message: text });
export function decodeRequirementReview(value: unknown) {
  return record(value).status === "unavailable" ? unavailableReview(value) : readyReview(value);
}

const node = requiredObject({ id: text, kind: text, body: text, section: text, requirement_id: text });
const basis = requiredObject({ id: text, job_id: text, source_hash: text, node_id: nullable(text), status: text });
export const decodeImpactPage = requiredObject({ basis, node: nullable(node),
  recorded: array(requiredObject({ target: node, path_total: optional(number),
    paths: array(requiredObject({ kind: literal("direct", "spec_review", "shared_decision"), nodes: array(node) })) })),
  total: number, offset: number, has_more: boolean, next_offset: number, message: text });
export const decodeImpactReport = requiredObject({ id: text, status: literal("running", "complete", "failed", "interrupted"),
  basis, stale: boolean, reason: optional(text), proposal: text, change_kind: text,
  inferred: array(requiredObject({ topic: text, effect: text, rationale: text, question: text,
    evidence: array(requiredObject({ node_id: text, quote: text })) })), limitations: array(text),
  coverage: requiredObject({ total: number, included: number, omitted: number, truncated: number, recorded_total: number, recorded_included: number }),
  sources: array(requiredObject({ node_id: text, kind: text, text, section: text })) });
