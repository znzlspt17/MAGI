export const jobId = "a".repeat(32), completedId = "c".repeat(64), sourceHash = "h".repeat(64);
export const request = "팀 주간 보고서와 의사결정을 기록하고 프로젝트별로 검색하는 서비스";
export const document = `# 팀 기록 서비스 명세\n\n## 요구사항\n\n- REQ-001: 사용자는 자신의 프로젝트 기록만 조회할 수 있다.\n- REQ-002: 보고서는 30일 동안 보관한다.\n\n## Architecture\n\nUse PostgreSQL to store notes. Check owner before reading.\n\n| 항목 | 정책 |\n| --- | --- |\n| 권한 | 소유자 확인 |\n| 보관 | 30일 |\n\n## 인수 조건\n\n다른 사용자 기록에는 접근할 수 없어야 한다.\n\n\`\`\`typescript\nconst report = { projectId: "example-project", retentionDays: 30 };\n\`\`\`\n`;
export const questions = ["[S] 우선 지원할 사용 환경을 선택해주세요.", "[M] 보고서에서 필요한 기능을 선택해주세요.", "[T] 추가로 지켜야 할 조건이 있나요?"];
export const questionForms = {
  S: { question_id: "S", question: questions[0], input_type: "single_choice", options: [{ id: "web", label: "웹 브라우저", impact: "설치 없이 팀에서 바로 사용합니다." }, { id: "app", label: "데스크톱 앱", impact: "설치와 업데이트 관리가 필요합니다." }], form_version: "1", recommendation: { option_ids: ["web"], reason: "팀 공유가 쉽습니다.", assumptions: ["인터넷에 연결된 환경"] } },
  M: { question_id: "M", question: questions[1], input_type: "multiple_choice", options: [{ id: "save", label: "보고서 저장" }, { id: "search", label: "프로젝트별 검색" }], form_version: "1" },
  T: { question_id: "T", question: questions[2], input_type: "text", options: [], form_version: "1" },
};
export function makeJob(status = "NEEDS_USER_INPUT", long = false) {
  return { id: jobId, request: long ? request.repeat(7) : request, project_id: "project", owner_id: "qa-user", status, execution_id: "execution", can_retry: true, reused_decision_count: 1,
    created_at: "2026-10-24T03:00:00Z", updated_at: "2026-10-24T04:00:00Z", final: document, candidate: document, critical: "# 보완 보고서\n보관 정책의 예외를 확인해야 합니다.",
    state: { status, candidate_hash: sourceHash, blocking_questions: questions, question_forms: questionForms, saved_answers: [],
      allowed_actions: ["answer", "message", "approve", "retry"], revision: 1,
      plan: { goal: "팀 기록 서비스 명세 정리", action: "ask_user", reason: "운영 조건을 확인하고 명세에 반영합니다.", tasks: [{ id: "retention", title: "보관 정책 확인", status: "blocked" }] },
      task_results: [{ action: "web_research", revision: 0, status: "completed", reason: "공식 자료의 링크를 기록했습니다." }], document_versions: [{ step_id: "spec", hash: sourceHash }] },
    execution_graph: { nodes: [{ id: "research", stage: "web_research", title: "외부 자료 조사", status: "completed", detail_available: true, execution_id: "execution" }, { id: "spec", stage: "spec_compile", title: "명세 작성", status: "completed", has_document: true, detail_available: true, execution_id: "execution" }] },
    latest_completed: { id: completedId, step_id: "approved" },
    completed_documents: [{ id: "approved", completed_id: completedId, title: "최종 승인 명세", has_document: true, detail_available: true }, { id: "approved-old", completed_id: "d".repeat(64), title: "이전 승인 명세", has_document: true, detail_available: true }],
    session_events: [{ id: "execution", action: "generate", input: { request }, summary: "요청을 분석하고 확인 질문을 준비했습니다.", questions, document_step_id: "spec", started_at: "2026-10-24T03:00:00Z" }, { id: "answer", action: "answer", input: { answers: [{ question_id: "RET", question: "보관 기간은 얼마인가요?", answer: "기본 보관 기간은 30일입니다." }] }, summary: "보관 정책을 명세에 반영했습니다." }],
  };
}
export const evidence = { item_id: "A", section: "Architecture", quote: "Check owner before reading.", start: 0, end: 27, line: 10, shared: true, provenance: "recorded_block" };
export const review = { status: "ready", message: "명세에 기록된 연결을 확인합니다.", basis: { id: "basis", source_hash: sourceHash }, review_status: "pending_approval", summary: { total: 2, spec_linked: 1, acceptance_linked: 1, verification_linked: 0 }, rows: [{ id: "REQ-001", text: "사용자별 프로젝트 기록 격리", group: "mandatory_requirements", spec_status: "linked", acceptance_status: "linked", verification_status: "unconfirmed", test_status: "not_collected", specification: [evidence], acceptance: [evidence], verification: [], specification_total: 1, acceptance_total: 1, verification_total: 0 }], unlinked: [], unlinked_total: 0, total: 1, has_more: false, offset: 0 };
export const decision = { id: "decision", version: 1, active: true, decision_id: "DEC-DB", text: "PostgreSQL을 사용해 팀 기록을 저장한다.", conditions: "서버를 운영하는 프로젝트에 적용", actor: "user", project_id: "project", job_id: jobId, completed_id: completedId, source_hash: sourceHash, source_available: true, evidence: [evidence] };
export const stats = { records: 30, calls: 29, pending_calls: 1, unknown_calls: 0, spent: "0.125", outstanding: "0.3", input_tokens: 42000, output_tokens: 12500, cached_tokens: 18000, input_recorded: 29, output_recorded: 29, cached_recorded: 29, missing_tokens: 0, missing_time: 0, uncertain: 1 };
export const nodes = [{ id: "req", kind: "requirement", job_id: jobId, active: true, body: "REQ-001 사용자별 프로젝트 기록 격리", attrs: { status: "confirmed", requirement_id: "REQ-001" } }, { id: "spec-node", kind: "spec", job_id: jobId, active: true, body: "소유자를 확인한 후 기록을 조회한다.", attrs: { artifact_hash: sourceHash, artifact_path: "spec.md" } }, { id: "decision-node", kind: "decision", job_id: jobId, active: true, body: "PostgreSQL 사용", attrs: { status: "proposed", rationale: "관계형 데이터로 권한을 연결합니다.", conditions: "서버 운영" } }];
export const edges = [{ id: "e1", source: "req", target: "spec-node", kind: "derived" }, { id: "e2", source: "spec-node", target: "decision-node", kind: "supports" }];
