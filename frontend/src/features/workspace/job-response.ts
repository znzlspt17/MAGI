import { array, boolean, dictionary, literal, number, object, optional, record, requiredObject, text } from "../../shared/api/response-contract";
import { decodeChangeReview } from "../execution/execution-detail";
import type { Job } from "../../shared/types";

const strings = array(text);
const step = requiredObject({ id: text, action: optional(text), title: optional(text), summary: optional(text),
  started_at: optional(text), completed_at: optional(text), stage: optional(text), status: optional(text),
  has_document: optional(boolean), detail_available: optional(boolean), execution_id: optional(text) });
const form = requiredObject({ question_id: text, question: text, input_type: literal("text", "single_choice", "multiple_choice"),
  options: array(requiredObject({ id: text, label: text, impact: optional(text), assumptions: optional(strings) })),
  recommendation: optional(requiredObject({ option_ids: strings, reason: text, assumptions: strings })), form_version: text });
const answer = requiredObject({ question_id: text, answer: text,
  selection: optional(requiredObject({ form_version: text, selected_option_ids: strings, custom_text: optional(text) })) });
const rubricReview = requiredObject({ score: number, score_reason: text, round: number, selected_round: number,
  selected_cycle: number, termination: literal("", "max_score", "patience", "round_budget"), requires_acceptance: boolean,
  evaluation_hash: text, revision_directives: strings,
  remaining_issues: array(requiredObject({ issue_id: text, severity: text, problem: text, required_change: text })),
  items: array(requiredObject({ rubric_id: text, requirement_id: text, condition: text,
    importance: literal("core", "critical", "secondary"), basis: array(requiredObject({ reference: text, quote: text })),
    verdict: literal("PASS", "FAIL", "UNDETERMINED"), section: text, quote: text, reason: text,
    evidence_kind: literal("quote", "absence") })) });
const state = object({ rubric_review: optional(rubricReview), execution_diagnostic: optional(requiredObject({ stop_code: text, target_action: text,
  block_reasons: strings, review_pass_count: number, review_pass_limit: number })), status: text, allowed_actions: strings, blocking_questions: strings, question_forms: dictionary(form),
  saved_answers: array(answer), review_questions: array(requiredObject({ question_id: text, requirement_ids: optional(strings),
    missing_information: optional(strings), resolution_reasons: optional(strings), problems: optional(strings), required_changes: optional(strings),
    evidence: optional(array(requiredObject({ source: text, quote: text }))) })),
  awaiting_input_reason: optional(text), candidate_hash: text, stop_reason: text, wait_reason: text, revision: number,
  plan: object({ goal: text, action: text, reason: text, tasks: array(requiredObject({ id: text, title: text, status: text })) }),
  task_results: array(requiredObject({ action: text, revision: number, status: optional(text), reason: optional(text) })),
  document_versions: array(requiredObject({ step_id: optional(text), hash: text })) });
const event = requiredObject({ id: text, action: text, retry_of: optional(text), status: optional(text), started_at: optional(text),
  summary: optional(text), questions: optional(strings), document_step_id: optional(text),
  input: optional(object({ request: text, feedback: text, answers: array(object({ question_id: text, question: text, answer: text })) })) });
const fields = object({ title: text, message: text, created_at: text, updated_at: text, queued_at: text, request: text, execution_id: text,
  action: text, retry_status: text, retry_action: text, error_code: text, read_only: boolean, can_continue: boolean, continuation_error: text,
  reused_decision_count: number, usage: record, can_retry: boolean, retry_requires_replay: boolean, retry_kind: literal("mcp", "model", "none"), retry_unavailable_reason: text,
  latest_completed: optional(object({ id: text, step_id: text })), completed_documents: array(step), state,
  change_review: optional(decodeChangeReview), session_events: array(event),
  execution_graph: requiredObject({ nodes: array(step), recording_incomplete: optional(boolean), unresolved_issue_counts: optional(dictionary(number)) }) });

export function decodeJob(value: unknown): Job {
  const source = record(value);
  return { ...fields(source), id: text(source.id), status: text(source.status) };
}
export const decodeJobs = array(decodeJob);
