import { expect, it } from "vitest";
import { decodeStepDetail } from "@/features/execution/execution-detail";

const modelCall = {
  id: "call-1", stage: "spec_compile", attempt: 1, status: "success",
  request_settings: { reasoning: { mode: "standard", effort: "medium", summary: "auto" }, verbosity: "high", max_output_tokens: 128000 },
  input_tokens: 42, output_tokens: 17, reasoning_tokens: 0, reasoning_summary: "확정 요구사항을 비교했습니다.\n다음 문장.", summary_truncated: false,
};

it("모델 호출별 설정과 nullable 추론 요약을 원형으로 보존한다", () => {
  const detail = decodeStepDetail({ model_calls: [modelCall, { ...modelCall, id: "call-2", attempt: 2,
    status: "failed", input_tokens: null, output_tokens: null, reasoning_tokens: null, reasoning_summary: null, summary_truncated: true }] });
  expect(detail.model_calls).toEqual([modelCall, { ...modelCall, id: "call-2", attempt: 2,
    status: "failed", input_tokens: null, output_tokens: null, reasoning_tokens: null, reasoning_summary: null, summary_truncated: true }]);
  expect(decodeStepDetail({}).model_calls).toBeUndefined();
  expect(decodeStepDetail({ model_calls: [] }).model_calls).toEqual([]);
});

it.each([
  { ...modelCall, reasoning_tokens: -1 }, { ...modelCall, attempt: 0 },
  { ...modelCall, reasoning_summary: { raw: "untrusted" } }, { ...modelCall, input_tokens: undefined },
  { ...modelCall, request_settings: { ...modelCall.request_settings, verbosity: "unknown" } },
])("잘못된 모델 호출을 해석 실패로 보고 다른 기록은 보존한다", invalid => {
  const detail = decodeStepDetail({ model_calls: [invalid], result: { wait_reason: "기존 기록" } });
  expect(detail.model_calls).toBeUndefined();
  expect(detail.response_incomplete).toBe(true);
  expect(detail.result?.wait_reason).toBe("기존 기록");
});

it("과거 단계는 유지하고 누락된 선택 필드를 허용한다", () => {
  expect(decodeStepDetail({ id: "old", stage: "legacy" })).toMatchObject({ id: "old", stage: "legacy" });
});

it("루브릭 집계만 해석하고 알 수 없는 모델 원문은 제외한다", () => {
  const detail = decodeStepDetail({ result: { rubric_summary: {
    status: "evaluated", policy_version: 1, item_count: 3, PASS: 2, FAIL: 1, UNDETERMINED: 0, raw: "MODEL_RAW",
  }, rubric_evaluation: { raw: "MODEL_RAW" } } });
  expect(detail.result?.rubric_summary?.FAIL).toBe(1);
  expect(JSON.stringify(detail)).not.toContain("MODEL_RAW");
});

it("잘못된 진단 목록을 화면으로 전달하지 않는다", () => {
  const detail = decodeStepDetail({ id: "stop", result: { stop_diagnostic: { issues: "invalid" } } });
  expect(detail.recording_incomplete).toBe(false);
  expect(detail.response_incomplete).toBe(true);
  expect(detail.result?.stop_diagnostic).toBeUndefined();
});

it("형식이 잘못된 최상위 응답은 실패한다", () => {
  expect(() => decodeStepDetail(["invalid"])).toThrow();
});
it("문서 기록이 훼손되어도 남은 진단은 표시한다", () => {
  const detail = decodeStepDetail({ id: "stop", document: { content: [] }, result: { wait_reason: "보완 한도" } });
  expect(detail.response_incomplete).toBe(true);
  expect(detail.document).toBeUndefined();
  expect(detail.result?.wait_reason).toBe("보완 한도");
});


it("문서 응답은 한국어 원본 언어를 엄격히 확인한다", () => {
  const content = "# 한국어 명세";
  expect(decodeStepDetail({ document: { content, language: "ko" } }).document).toMatchObject({ content, language: "ko" });
  for (const language of ["en", "unknown", null]) {
    const detail = decodeStepDetail({ document: { content, language } });
    expect(detail.document).toBeUndefined();
    expect(detail.response_incomplete).toBe(true);
  }
});

it("nullable 진단 필드는 보존하고 저장 누락과 응답 해석 실패를 구분한다", () => {
  const detail = decodeStepDetail({ recording_incomplete: false, result: { diagnostic: {
    error_code: "REVIEW_VALIDATION_FAILED", error_stage: "checklist_critic", failed_checks: ["rubric_stale"],
    validation_reason: "evaluation_draft_mismatch", category: "prerequisite_stale",
    validation_section: null, validation_index: null, validation_field: null,
    attempts: [{ attempt: 1, error_code: null, error_stage: "checklist_critic", failed_checks: ["rubric_stale"], validation_reason: "evaluation_draft_mismatch" }],
  } } });
  expect(detail.recording_incomplete).toBe(false);
  expect(detail.response_incomplete).toBe(false);
  expect(detail.result?.diagnostic?.validation_reason).toBe("evaluation_draft_mismatch");
  expect(detail.result?.diagnostic?.attempts?.[0].attempt).toBe(1);
});
