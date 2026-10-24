import type { ConversationTurn, Job, SessionEvent } from "./types";

export function conversationTurns(job: Job): { turns: ConversationTurn[]; incomplete: boolean } {
  const records = new Map<string, SessionEvent>();
  let incomplete = false;
  for (const event of job.session_events || []) {
    if (!event || typeof event.id !== "string" || !event.id) { incomplete = true; continue; }
    // 같은 실행의 갱신은 기존 순서를 유지하며 최신 공개 요약으로 대체한다.
    records.set(event.id, event);
  }
  const turns: ConversationTurn[] = [];
  for (const event of records.values()) {
    const answers = (event.input?.answers || []).filter((answer) => typeof answer.answer === "string" && answer.answer.trim());
    const directText = event.input?.request || event.input?.feedback;
    const text = directText || (answers.length ? "" : event.action === "approve" ? "이 명세를 승인했습니다." : "");
    if (text || answers.length) turns.push({ id: `${event.id}:user`, eventId: event.id, role: "user", text, ...(!directText && answers.length ? { answers } : {}), timestamp: event.started_at, action: event.action });
    const questions = (event.questions || []).filter((q) => typeof q === "string" && q.trim());
    if (event.summary || questions.length || event.document_step_id) turns.push({ id: `${event.id}:magi`, eventId: event.id, role: "magi", text: event.summary || "", questions, documentStepId: event.document_step_id, timestamp: event.started_at });
  }
  if (!records.size) {
    incomplete = true;
  }
  return { turns, incomplete };
}
