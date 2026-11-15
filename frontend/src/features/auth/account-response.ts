import { array, boolean, literal, number, object, optional, requiredObject, text } from "../../shared/api/response-contract";

export const decodeAuthInfo = requiredObject({ public: boolean, login_available: optional(boolean) });
export const decodeUser = requiredObject({ id: text, role: text, csrf: optional(text), identity_kind: optional(literal("guest", "google")), owner_ids: optional(array(text)) });
export const decodeServiceStatus = object({ ready: boolean, active_count: number, queued_count: number, max_parallel: number, own_active_count: number });
export const decodeUsage = object({ limit_mode: literal("observe"), daily_runs: number, runs_exceeded: boolean, runs: number,
  remaining_runs: number, resets_at: text, limit_reached: boolean });
