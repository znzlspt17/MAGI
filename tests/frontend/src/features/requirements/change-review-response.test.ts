import { expect, it } from "vitest";
import { decodeChangeReview } from "@/features/execution/execution-detail";

const change = { id: "C", change: "modified", before: null, after: null, status: "analysed", reason: "", question: "어떻게 할까요?" };
const report = (value: object) => ({ status: "complete", after_hash: "h", analysed: 1, remaining: 0, sources: [], changes: [{ ...change, ...value }] });
const form = { question_id: "C", question: change.question, form_version: "v1", input_type: "single_choice",
  options: [{ id: "a", label: "유지", impact: null }, { id: "b", label: "변경" }], recommendation: null };

it("과거 폼 누락·null과 유효한 신규 폼을 받아들인다", () => {
  expect(decodeChangeReview(report({})).changes[0].question_form).toBeUndefined();
  expect(decodeChangeReview(report({ question_form: null })).changes[0].question_form).toBeUndefined();
  const decoded = decodeChangeReview(report({ question_form: form })).changes[0].question_form;
  expect(decoded?.options.map(option => option.label)).toEqual(["유지", "변경"]);
  expect(decoded?.options[0].impact).toBeUndefined();
});

it.each([
  {}, { ...form, input_type: "unknown" }, { ...form, form_version: "" },
  { ...form, question_id: "other" }, { ...form, question: "다른 질문" },
  { ...form, options: form.options.slice(0, 1) }, { ...form, options: [form.options[0], form.options[0]] },
  { ...form, options: [{ id: "a", label: "" }, form.options[1]] },
  { ...form, recommendation: { option_ids: ["unknown"], reason: "이유", assumptions: [] } },
])("존재하지만 잘못된 제안 폼은 거부한다", value => {
  expect(() => decodeChangeReview(report({ question_form: value }))).toThrow();
});
