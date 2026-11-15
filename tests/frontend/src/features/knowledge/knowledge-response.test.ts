import { expect, it } from "vitest";
import { decodeKnowledgeGraph, decodeSearch } from "@/features/knowledge/knowledge-response";

it("지식 조회 응답의 색인 상태와 반영 버전을 보존한다", () => {
  const index = { index_status: "pending", index_source_revision: 4, index_applied_revision: 3 };
  expect(decodeKnowledgeGraph({ nodes: [], edges: [], ...index })).toMatchObject(index);
  expect(decodeSearch({ nodes: [], ...index })).toMatchObject(index);
  expect(() => decodeSearch({ nodes: [], index_status: "invalid" })).toThrow();
});
