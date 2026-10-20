export interface User {
  id: string;
  role: string;
  csrf?: string;
}
export interface ServiceStatus {
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
  options: { id: string; label: string }[];
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
  execution_graph?: {
    nodes: Step[];
    legacy?: boolean;
    recording_incomplete?: boolean;
    unresolved_issue_counts?: Record<string, number>;
  };
}
