import { array, boolean, dictionary, literal, nullable, number, object, optional, record, requiredObject, text } from "../../shared/api/response-contract";

const strings = array(text);
const adminUser = requiredObject({ id: text, role: optional(text), daily_runs: optional(number), daily_usd: optional(text), suspended: optional(boolean) });
export const decodeOverview = object({ embedding_status: text, users: array(adminUser),
  executions: array(requiredObject({ execution_id: text, job_id: text, kind: text, phase: text, stopping: optional(boolean) })) });

const jobFields = { id: text, request: optional(text), status: optional(text), owner_id: optional(text), created_at: optional(text) };
export const decodeCatalog = requiredObject({ jobs: array(requiredObject(jobFields)), pending: strings });
export const decodeAdminJob = requiredObject({ ...jobFields, final: optional(text), candidate: optional(text), critical: optional(text),
  session_events: optional(array(object({ id: text, action: text, retry_of: text, status: text, started_at: text, summary: text,
    questions: strings, document_step_id: text, input: object({ request: text, feedback: text,
      answers: array(object({ question_id: text, question: text, answer: text })) }) }))) });
export const decodeCleanup = requiredObject({ id: text, scope: text, targets: optional(strings),
  counts: requiredObject({ jobs: number, files: optional(number), project_decisions: optional(number) }),
  external_references: optional(number), skipped: optional(array((value: unknown) => value)) });
export const decodeCleanupResult = requiredObject({ state: text });

const logRow = requiredObject({ timestamp: text, service: text, level: text, event: text, message: text, fields: dictionary(text) });
export const decodeLogPage = requiredObject({ items: array(logRow), start: text, end: text, next_offset: nullable(number),
  storage: requiredObject({ state: text }) });
export const decodeLogStatus = requiredObject({ state: text, retention_days: number, collector_seen: boolean, free_bytes: nullable(number), warnings: strings });
const validation = requiredObject({ record_id: text, created_at: nullable(text), execution_id: nullable(text),
  execution_link: literal("confirmed", "unconfirmed"), state: literal("recognized", "unrecognized", "unreadable"), stage: text,
  error_code: nullable(text), failed_checks: strings, attempt: nullable(number), validation_field: optional(text),
  validation_reason: nullable(text), validation_section: nullable(text), validation_index: nullable(number) });
export const decodeValidationPage = requiredObject({ items: array(validation), offset: number, limit: number, next_offset: nullable(number) });

const statsFields = { records: number, calls: number, pending_calls: number, unknown_calls: number, spent: text, outstanding: text,
  input_tokens: nullable(number), output_tokens: nullable(number), cached_tokens: nullable(number), input_recorded: number,
  output_recorded: number, cached_recorded: number, missing_tokens: number, missing_time: number, uncertain: number };
export const decodeUsageSummary = requiredObject({ start: text, end: text, summary: requiredObject(statsFields),
  daily: array(requiredObject({ ...statsFields, day: text })),
  today: requiredObject({ day: text, spent: text, outstanding: text, limit: text }), users: array(requiredObject({ id: text })) });
const usageFields = object({ ...statsFields, id: text, job_id: text, request: text, model: text, state: text, actual: nullable(text), reserved: text,
  called_at: nullable(text), reserved_at: nullable(text), settled_at: nullable(text), settlement_source: nullable(literal("calculated", "manual")),
  cost_policy: nullable(text), cost_evidence: literal("manual", "unknown", "complete", "missing_usage", "invalid_usage"),
  cache_write_tokens: nullable(number), cache_write_30m_tokens: nullable(number), cache_write_12h_tokens: nullable(number),
  usage_day: text, latest_day: text, latest_at: nullable(text), is_call: boolean });
function usageRow(value: unknown) {
  const source = record(value);
  return { ...usageFields(source), user_id: text(source.user_id) };
}
export const decodeUsageRows = requiredObject({ rows: array(usageRow), total: number, limit: optional(number), offset: optional(number) });
