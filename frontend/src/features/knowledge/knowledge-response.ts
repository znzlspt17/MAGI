import { array, boolean, number, object, optional, requiredObject, text } from "../../shared/api/response-contract";
import type { KnowledgeNode } from "./graph-data";

export const decodeProject = requiredObject({ id: text, name: text });
export const decodeProjects = array(decodeProject);
export const decodeSessions = array(requiredObject({ id: text, request: optional(text), status: optional(text), title: optional(text) }));
const edge = requiredObject({ id: optional(text), source: text, target: text, kind: text, other_body: optional(text) });
const node = requiredObject({ id: text, kind: text, body: text, job_id: optional(text), logical_key: optional(text), active: optional(boolean),
  attrs: optional(object({ requirement_id: text, question: text, section: text, artifact_hash: optional(text), artifact_path: text,
    status: text, origin: text, rationale: text, conditions: text, original_text: text, sources: array(text) })),
  matches: optional(array(requiredObject({ quote: text }))), document: optional(text), document_has_more: optional(boolean),
  document_next_offset: optional(number), title: optional(text), project_id: optional(text), edges: optional(array(edge)) });
export const decodeKnowledgeNode: (value: unknown) => KnowledgeNode = node;
export const decodeKnowledgeGraph = requiredObject({ nodes: array(node), edges: array(edge), has_more: optional(boolean) });
export const decodeSearch = requiredObject({ nodes: array(node) });
export const decodeDocumentPage = requiredObject({ content: text, has_more: boolean, next_offset: number });
