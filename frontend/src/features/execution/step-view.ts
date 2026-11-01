import type { Step } from "../../shared/types";
import type { StepDetail, StepResultData } from "./execution-detail";

const titles: Record<string, string> = {
    request: "요청 접수",
    planner: "작업 계획",
    project_context: "프로젝트 자료 확인",
    knowledge_search: "기존 근거 확인",
    web_research: "외부 자료 조사",
    ask_user: "사용자 결정 확인",
    blocked: "진행 중단",
    requirement_lock_stage: "요구사항 확정",
    generate: "요청 접수",
    interview: "요청 분석",
    await_user: "요구사항 확인 필요",
    answer: "답변 저장",
    requirement_lock: "요구사항 확정",
    revise: "수정 의견",
    spec_compile: "명세 생성",
    checklist_critic: "명세 검토",
    review_resolution: "해결 방법 판단",
    approve: "최종 승인",
    compose_candidate: "검토본 준비",
    critical_report: "명세 진행 중단 보고",
  };
titles.workflow = "실행 흐름";
export const stageLabel = (node?: Step) => node?.title || titles[node?.stage || ""] || "실행 단계";

type Content =
  | { kind: "plan"; plan: StepResultData["plan"] }
  | { kind: "research"; research: StepDetail["research"] }
  | { kind: "resolution"; action: string | undefined }
  | { kind: "record" | "legacy" };

export function stepContent(node: Step | undefined, detail: StepDetail): Content {
  switch (node?.stage) {
    case "planner": return { kind: "plan", plan: detail.result?.plan };
    case "web_research": return { kind: "research", research: detail.research || detail.result?.research };
    case "review_resolution": return { kind: "resolution", action: detail.result?.action };
    default: return { kind: node?.stage && !titles[node.stage] ? "legacy" : "record" };
  }
}

export function requirementGroups(result: StepResultData): { title: string; items: string[] }[] {
  const source = result.requirements || result;
  const groups = Array.isArray(source) ? [{ title: "확정 요구사항", items: source }] : [
    { title: "필수 요구사항", items: source.mandatory_requirements },
    { title: "권장 요구사항", items: source.recommended_requirements },
    { title: "선택 요구사항", items: source.optional_requirements },
    { title: "제약 조건", items: source.constraints },
  ];
  return groups.filter(group => group.items?.length).map(group => ({ title: group.title,
    items: (group.items || []).map(item => typeof item === "string" ? item : `${item.id || ""} ${item.text || ""}`),
  }));
}
