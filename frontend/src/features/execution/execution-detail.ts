import { array, boolean, number, object, optional, record, text, requiredObject, literal, nullable } from "../../shared/api/response-contract";

const strings = array(text);
const requirement = (value: unknown) => typeof value === "string" ? value : object({ id: text, text })(value);
const requirements = array(requirement);
const groups = object({ mandatory_requirements: requirements, recommended_requirements: requirements, optional_requirements: requirements, constraints: requirements });
const evidence = (value: unknown) => typeof value === "string" ? value : object({ source: text, quote: text })(value);
const issue = object({ issue_id: text, requirement_id: optional(text), problem: text, title: text, severity: text, lifecycle: text,
  section: text, defect_kind: text, resolution_reason: text, resolution_kind: text, decision_answer_id: optional(text),
  missing_information: text, decision_key: text, required_change: text, basis_refs: strings, rubric_ids: strings,
  evidence: value => Array.isArray(value) ? value.map(evidence) : value == null ? [] : [evidence(value)] });
const attempt = object({ review_round: number, proposed_change: text, outcome: text });
const diagnosticIssue = object({ issue_id: text, requirement_id: optional(text), problem: text, required_change: text,
  resolution_reason: text, resolution_kind: text, basis_refs: strings, decision_answer_id: optional(text), attempts: array(attempt) });
const stop = object({ stop_reason: text, cause: text, next_check: text, recording_incomplete: boolean, work_scope: text,
  issues: array(diagnosticIssue), completed_work: array(object({ action: text, count: number })) });
const plan = object({ goal: text, reason: text, action: text, target: text, expected_result: text,
  tasks: array(object({ id: text, title: text, status: text })), input_refs: strings, affected_requirement_ids: strings });
const research = requiredObject({ search_method: optional(text), mode: text, performed: boolean, outcome: literal("skipped", "no_results", "failed", "links_found"), reason: text, query: text,
  retrieved_at: text, result_count: number, sources: array(requiredObject({ title: text, url: text, query: text, retrieved_at: text })) });
const resultFields = {
  requirements: (value: unknown) => Array.isArray(value) ? requirements(value) : groups(value),
  mandatory_requirements: requirements, recommended_requirements: requirements, optional_requirements: requirements, constraints: requirements,
  plan, action: text, stop_diagnostic: stop, wait_reason: text, summary: text, purpose: text, request: text, feedback: text,
  diagnostic: object({ error_code: text, error_stage: text, failed_checks: strings }),
  rubric_summary: object({ status: literal("ready", "evaluated"), policy_version: number, item_count: number,
    PASS: number, FAIL: number, UNDETERMINED: number }),
  answers: array(object({ question: text, answer: text, question_id: text })), questions: strings, blocking_questions: strings,
  issues: array(issue), resolved_issues: array(issue), report: text, research,
};
const decodeResult = object(resultFields);
const location = requiredObject({ item_id: text, section: text, text, start: number, end: number, line: number, requirement_ids: strings, decision_ids: strings });
const changeQuestionForm = requiredObject({ question_id: text, question: text, form_version: text,
  input_type: literal("text", "single_choice", "multiple_choice"),
  options: array(requiredObject({ id: text, label: text, impact: optional(nullable(text)), assumptions: optional(strings) })),
  recommendation: optional(nullable(requiredObject({ option_ids: strings, reason: text, assumptions: strings }))) });
function decodeChangeQuestionForm(value: unknown) {
  const form = changeQuestionForm(value);
  const ids = form.options.map(option => option.id);
  const labels = form.options.map(option => option.label.trim());
  const recommended = form.recommendation?.option_ids;
  if (![form.question_id, form.question, form.form_version, ...ids, ...labels].every(item => item.trim()) ||
      new Set(ids).size !== ids.length || new Set(labels).size !== labels.length ||
      (form.input_type === "text" ? ids.length !== 0 : ids.length < 2) ||
      (recommended && (form.input_type === "text" || recommended.length === 0 ||
        new Set(recommended).size !== recommended.length || recommended.some(id => !ids.includes(id)) ||
        (form.input_type === "single_choice" && recommended.length !== 1)))) {
    throw new Error("확인 제안의 질문 형식이 올바르지 않습니다.");
  }
  return form;
}
const change = requiredObject({ id: text, change: literal("added", "removed", "modified", "moved"), before: nullable(location), after: nullable(location),
    status: literal("analysed", "unanalysed"), reason: text, meaning: optional(literal("wording", "semantic", "uncertain")),
    relation: optional(literal("direct", "related", "unverified")), summary: optional(text), rationale: optional(text), question: optional(text), diff: optional(text),
    question_form: optional(nullable(decodeChangeQuestionForm)),
    evidence: optional(array(requiredObject({ source_id: text, quote: text }))) });
function decodeChange(value: unknown) {
  const parsed = change(value);
  if (parsed.question_form && (parsed.question_form.question_id !== parsed.id || parsed.question_form.question !== parsed.question)) {
    throw new Error("확인 제안과 질문 폼이 일치하지 않습니다.");
  }
  return parsed;
}
export const decodeChangeReview = requiredObject({ status: literal("no_baseline", "unchanged", "complete", "partial", "failed", "running"),
  before_id: optional(nullable(text)), after_id: optional(text), before_hash: optional(nullable(text)), after_hash: text,
  analysed: number, remaining: nullable(number), sources: array(requiredObject({ source_id: text, text, question: optional(text) })),
  changes: array(decodeChange) });
const detailFields = { id: text, stage: text, status: text, title: text, summary: text, recording_incomplete: boolean,
  unavailable: boolean, message: text, result: decodeResult, research,
  document: requiredObject({ content: text, filename: optional(text), language: literal("ko"), kind: optional(text), source_hash: optional(text), completed_id: optional(text) }),
  usage: record, change_review: decodeChangeReview };
const decodeDetail = object(detailFields);
export type StopDiagnosticData = ReturnType<typeof stop>;
export type IssueData = ReturnType<typeof issue>;
export type StepResultData = ReturnType<typeof decodeResult>;
export type StepDetail = ReturnType<typeof decodeDetail>;

export function decodeStepDetail(value: unknown): StepDetail {
  const raw = record(value);
  const result: Record<string, unknown> = {};
  let incomplete = false;
  if (raw.result !== undefined) {
    try {
      const input = record(raw.result);
      for (const [key, decode] of Object.entries(resultFields)) {
        if (input[key] === undefined) continue;
        try { result[key] = decode(input[key]); } catch { incomplete = true; }
      }
    } catch { incomplete = true; }
  }
  const captured: Record<string, unknown> = {};
  for (const [key, decode] of Object.entries(detailFields)) {
    if (key === "result" || raw[key] === undefined) continue;
    try { captured[key] = decode(raw[key]); } catch { incomplete = true; }
  }
  return decodeDetail({ ...captured, result, recording_incomplete: incomplete || raw.recording_incomplete === true });
}
