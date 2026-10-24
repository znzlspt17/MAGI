export type UsageStats = {
  records: number; calls: number; pending_calls: number; unknown_calls: number;
  spent: string; outstanding: string;
  input_tokens: number | null; output_tokens: number | null; cached_tokens: number | null;
  input_recorded: number; output_recorded: number; cached_recorded: number;
  missing_tokens: number; missing_time: number; uncertain: number;
};
export type UsageSummary = {
  start: string; end: string; summary: UsageStats;
  daily: (UsageStats & { day: string })[];
  today: { day: string; spent: string; outstanding: string; limit: string };
  users: { id: string }[];
};
export type UsageRow = Partial<UsageStats> & {
  id?: string; user_id: string; job_id?: string; request?: string;
  model?: string; state?: string; actual?: string | null; reserved?: string;
  called_at?: string | null; reserved_at?: string | null; settled_at?: string | null;
  settlement_source?: "calculated" | "manual" | null;
  cost_policy?: string | null;
  cost_evidence?: "manual" | "unknown" | "complete" | "missing_usage" | "invalid_usage";
  cache_write_tokens?: number | null; cache_write_30m_tokens?: number | null; cache_write_12h_tokens?: number | null;
  usage_day?: string; latest_day?: string; latest_at?: string | null; is_call?: boolean;
};
export type UsageRows = { rows: UsageRow[]; total: number; limit: number; offset: number };
export type Group = "job" | "user" | "call";
export const count = (value: number | null | undefined) => value == null ? "기록 없음" : value.toLocaleString("ko-KR");

export function settlementLabel(row: UsageRow) {
  if (row.settlement_source === "manual") return "수동 정산";
  if (row.settlement_source === "calculated" && row.cost_evidence === "complete") return "사용량 기반 산정";
  if (row.cost_evidence === "missing_usage" || row.cost_evidence === "invalid_usage") return "정산 근거 불완전";
  return "정산 근거 기록 없음";
}

// 금액은 문자열로 보존하고 차트 좌표를 만들 때만 Number로 변환한다.
export function money(value: string | undefined | null) {
  if (value == null) return "미정";
  const [whole, fraction = ""] = value.split(".");
  return "$" + (whole || "0").replace(/\B(?=(\d{3})+(?!\d))/g, ",") + "." + fraction.padEnd(8, "0");
}
export function koreaToday() {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}
export function presetRange(preset: string, today = koreaToday()) {
  const end = today, date = new Date(today + "T00:00:00Z");
  if (preset === "month") date.setUTCDate(1);
  else date.setUTCDate(date.getUTCDate() - (preset === "30" ? 29 : preset === "today" ? 0 : 6));
  return { start: date.toISOString().slice(0, 10), end };
}
export function validRange(start: string, end: string) {
  const days = (Date.parse(end) - Date.parse(start)) / 86400000;
  return Number.isFinite(days) && days >= 0 && days < 366;
}
export function timestamp(value: string | null | undefined) {
  return value ? new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", dateStyle: "short", timeStyle: "medium", hour12: false }).format(new Date(value)) : "시각 기록 없음";
}
