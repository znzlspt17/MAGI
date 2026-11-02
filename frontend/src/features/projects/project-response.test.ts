import { expect, it } from "vitest";
import { decodeDecisionCandidates, decodeDecisions, decodeReusedDecisions } from "./project-response";

const candidate = { decision_id: "d", text: "Use PostgreSQL.", conditions: "", actor: "user", job_id: "j", project_id: "p",
  completed_id: "c", source_hash: "h", evidence: [{ item_id: "i", section: "architecture", quote: "Use PostgreSQL." }] };
const registered = { ...candidate, id: "r", version: 1, active: true };
const page = { total: 1, next_offset: null, project_id: "p" };

it("등록 전 후보에는 등록 후 필드를 요구하지 않는다", () => {
  expect(decodeDecisionCandidates({ ...page, rows: [candidate] }).rows).toEqual([candidate]);
});
it("재사용 사본에 현재 등록 상태를 보충하지 않는다", () => {
  const snapshot = { ...candidate, id: "r", version: 1 };
  expect(decodeReusedDecisions({ rows: [snapshot], total: 1, next_offset: null }).rows).toEqual([snapshot]);
  expect(decodeReusedDecisions({ rows: [], total: 0, next_offset: null }).rows).toEqual([]);
});
it("등록 결정의 식별자·버전·상태·프로젝트는 필수로 유지한다", () => {
  expect(decodeDecisions({ ...page, rows: [registered] }).rows).toEqual([registered]);
  for (const key of ["id", "version", "active"]) {
    const row: Record<string, unknown> = { ...registered }; delete row[key];
    expect(() => decodeDecisions({ ...page, rows: [row] })).toThrow();
  }
  expect(() => decodeDecisions({ rows: [], total: 0, next_offset: null })).toThrow();
});
it("각 응답에서 필수 출처와 잘못된 타입을 계속 거부한다", () => {
  for (const decode of [decodeDecisions, decodeDecisionCandidates, decodeReusedDecisions]) {
    expect(() => decode({ ...page, rows: [{ ...registered, decision_id: undefined }] })).toThrow();
    expect(() => decode({ ...page, rows: [{ ...registered, source_hash: {} }] })).toThrow();
    expect(() => decode({ ...page, rows: [{ ...registered, actor: "unknown" }] })).toThrow();
  }
  expect(() => decodeReusedDecisions({ ...page, rows: [candidate] })).toThrow();
  expect(() => decodeReusedDecisions({ ...page, rows: [{ ...registered, version: "1" }] })).toThrow();
  expect(() => decodeDecisionCandidates({ rows: [], total: 0, next_offset: null })).toThrow();
});
