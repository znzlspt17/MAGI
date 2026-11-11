import { describe, expect, it } from "vitest";
import { workspaceStage, workspaceStageMessage } from "@/features/workspace/progress-state";

describe("작업 상태에 따른 안내 단계", () => {
  it("새 요청과 사용자 결정, 승인 후보, 완료 상태를 구분한다", () => {
    expect(workspaceStage(null)).toBe("request");
    expect(workspaceStage({ id: "j", status: "NEEDS_USER_INPUT", state: { blocking_questions: ["질문"] } })).toBe("questions");
    expect(workspaceStage({ id: "j", status: "PASS_PENDING_USER_APPROVAL" })).toBe("review");
    expect(workspaceStage({ id: "j", status: "FINALIZED" })).toBe("final");
  });
  it("재질문과 승인 재시도를 완료 상태보다 현재 상태에 맞춰 표시한다", () => {
    expect(workspaceStage({ id: "j", status: "NEEDS_USER_INPUT", latest_completed: { id: "old" } })).toBe("questions");
    expect(workspaceStage({ id: "j", status: "error", retry_status: "PASS_PENDING_USER_APPROVAL" })).toBe("review");
  });
  it("이전 질문 기록이 남아 있어도 현재 승인과 확정 상태를 우선한다", () => {
    expect(workspaceStage({ id: "j", status: "PASS_PENDING_USER_APPROVAL", state: { status: "PASS_PENDING_USER_APPROVAL", blocking_questions: ["이전 질문"] } })).toBe("review");
    expect(workspaceStage({ id: "j", status: "FINALIZED", state: { status: "FINALIZED", blocking_questions: ["이전 질문"] } })).toBe("final");
  });
  it("실행 중이거나 상태가 불확실하면 이전 단계를 추측하지 않는다", () => {
    expect(workspaceStage({ id: "j", status: "running", state: { status: "PASS_PENDING_USER_APPROVAL" } })).toBeNull();
    expect(workspaceStage({ id: "j", status: "error" })).toBeNull();
  });
  it("알려진 실행 및 중단 상태를 로딩으로 잘못 안내하지 않는다", () => {
    expect(workspaceStageMessage({ id: "j", status: "running" })).toBe("요청을 처리하고 있습니다");
    expect(workspaceStageMessage({ id: "j", status: "queued" })).toBe("실행 순서를 기다리고 있습니다");
    expect(workspaceStageMessage({ id: "j", status: "error" })).toBe("작업이 중단되었습니다. 아래에서 복구 방법을 확인하세요");
    expect(workspaceStageMessage(null)).toBe("현재 작업 상태를 확인하고 있습니다");
  });
});
