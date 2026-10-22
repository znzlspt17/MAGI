export interface User {
  id: string;
  role: string;
  csrf?: string;
}
export interface ServiceStatus {
  phase?: "idle" | "running" | "waiting" | "recovery";
  checkState?: "loading" | "ready" | "error";
  busy?: boolean;
  mine?: boolean;
  recovering?: boolean;
  deadline?: number;
}
export interface Usage {
  runs?: number;
  remaining_runs?: number;
  resets_at?: string;
  limit_reached?: boolean;
  [key: string]: unknown;
}
export interface QuestionForm {
  question_id: string;
  question: string;
  input_type: "text" | "single_choice" | "multiple_choice";
  options: { id: string; label: string; impact?: string | null; assumptions?: string[] }[];
  recommendation?: { option_ids: string[]; reason: string; assumptions: string[] } | null;
  form_version: string;
}
export interface DocumentData {
  content: string;
  filename?: string;
  language?: string;
  source_hash?: string;
  kind?: string;
}
// 서버의 저장 이력은 단계별로 다른 결과를 가진다. 구체적인 필드는 소비 위치에서 검사한다.
export type RecordData = Record<string, any>;
export interface ResearchRecord {
  search_method?: string;
  mode: string; performed: boolean; outcome: "skipped" | "no_results" | "failed" | "links_found";
  reason: string; query: string; retrieved_at: string; result_count: number;
  sources: { title: string; url: string; query?: string; retrieved_at?: string }[];
}
export interface Step extends RecordData {
  id: string;
  stage?: string;
  status?: string;
  has_document?: boolean;
  detail_available?: boolean;
  execution_id?: string;
}
export interface Job extends RecordData {
  id: string;
  request?: string;
  status: string;
  execution_id?: string;
  state?: RecordData;
  change_review?: ChangeReviewData;
  session_events?: SessionEvent[];
  execution_graph?: {
    nodes: Step[];
    legacy?: boolean;
    recording_incomplete?: boolean;
    unresolved_issue_counts?: Record<string, number>;
  };
}

export interface ChangeLocation {
  item_id: string; section: string; text: string; start: number; end: number; line: number;
  requirement_ids: string[]; decision_ids: string[];
}
export interface SpecChange {
  id: string; change: "added" | "removed" | "modified" | "moved";
  before: ChangeLocation | null; after: ChangeLocation | null;
  status: "analysed" | "unanalysed"; reason: string;
  meaning?: "wording" | "semantic" | "uncertain";
  relation?: "direct" | "related" | "unverified";
  summary?: string; rationale?: string; question?: string; diff?: string;
  evidence?: { source_id: string; quote: string }[];
}
export interface ChangeReviewData {
  status: "no_baseline" | "unchanged" | "complete" | "partial" | "failed" | "running";
  before_id?: string | null; after_id?: string; before_hash?: string | null; after_hash: string;
  legacy?: boolean; analysed: number; remaining: number | null;
  sources: { source_id: string; text: string; question?: string }[];
  changes: SpecChange[];
}

export interface SessionEvent {
  id: string;
  action: string;
  input?: {
    request?: string;
    feedback?: string;
    answers?: { question_id?: string; question?: string; answer?: string }[];
  };
  status?: string;
  started_at?: string;
  summary?: string;
  questions?: string[];
  document_step_id?: string;
}

export interface ConversationTurn {
  id: string;
  eventId: string;
  role: "user" | "magi";
  text: string;
  answers?: NonNullable<NonNullable<SessionEvent["input"]>["answers"]>;
  timestamp?: string;
  action?: string;
  questions?: string[];
  documentStepId?: string;
}
