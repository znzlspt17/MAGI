"""저장용 출처와 모델용 짧은 참조를 분리한다."""

from copy import deepcopy
import json
import re

from backend.errors import ArtifactError, RequirementNormalizationError, ReviewValidationError, SpecCompilationError


PATH = "state/prompt_references.json"
REFERENCE_FIELDS = {"source", "sources", "basis_refs", "conflicting_source", "reused_node_ids"}
INTERNAL_FIELDS = {"lock_id", "source_refs", "draft_hash", "feedback_hash", "project_id", "job_id",
                   "chunk_id", "source_ranges", "created_at", "updated_at"}
SHEET_FIELDS = {"request_type", "request_summary", "mandatory_requirements", "recommended_requirements",
                "optional_requirements", "constraints", "non_scope", "assumptions", "user_answers",
                "acceptance_criteria_seed", "unresolved_questions", "decisions"}
ISSUE_FIELDS = {"issue_id", "section", "severity", "blocking", "checklist_id", "problem", "required_change",
                "requirement_id", "evidence", "status", "decision_key"}
CANONICAL_FIELDS = {
    "interview": {"file_count", "files", "request_types", "saved_answers", "validated_requirements"},
    "requirement_lock": {"project_manifest", "request_type", "assumptions", "saved_answers",
                         "unresolved_blocking_questions", "previous_lock_sheet"},
    "spec_compile": {"file_count", "files", "requirement_lock_sheet", "previous_trace"},
    "checklist_critic": {"requirement_lock_sheet", "previous_issues"},
    "review_resolution": {"issues", "confirmed_basis", "previous_resolutions", "review_questions", "diagnose_keys"},
}
REFERENCE_RULES = (
    "Reference actual user inputs using supplied S references and retrieved knowledge using supplied K references. "
    "Use only references supplied for this call in source, sources, basis_refs, conflicting_source and reused_node_ids. "
    "Keep requirement, workflow, decision and issue IDs unchanged. K references are proposals, never user confirmation. "
    "Input fields ending in _source point to supplied original text; reproduce that exact text when the output schema requires original_text. "
    "Do not put source/knowledge references or storage metadata in product prose."
)


class PromptContext:
    def __init__(self, writer=None):
        self.writer = writer
        self.data = {"sources": {}, "knowledge": {}}
        if writer is not None and writer.path(PATH).exists():
            try:
                self.data = writer.read_json(PATH)
                for group, prefix in (("sources", "S"), ("knowledge", "K")):
                    entries = self.data[group]
                    if not isinstance(entries, dict) or any(
                        not re.fullmatch(prefix + r"[1-9]\d*", key) or not isinstance(value, dict)
                        or (group == "sources" and (not isinstance(value.get("text"), str)
                            or not isinstance(value.get("aliases"), list)
                            or not all(isinstance(alias, str) for alias in value["aliases"])))
                        or (group == "knowledge" and not isinstance(value.get("id"), str))
                        for key, value in entries.items()
                    ):
                        raise ValueError()
            except (OSError, ValueError, TypeError, KeyError):
                raise ArtifactError("모델 출처 대응표를 읽을 수 없습니다.") from None
        self.available = {"sources": set(), "knowledge": set()}
        self.aliases = {}
        self.source_items = {}
        self.semantic_ids = set()
        self.basis_source_aliases = set()
        self.stage = None

    def source(self, alias, text, *, question=""):
        if not isinstance(text, str) or not text:
            return None
        entries = self.data["sources"]
        ref = next((key for key, entry in entries.items() if entry["text"] == text), None)
        if ref is None:
            ref = "S" + str(max((int(key[1:]) for key in entries), default=0) + 1)
            entries[ref] = {"text": text, "aliases": []}
        if alias not in entries[ref]["aliases"]:
            entries[ref]["aliases"].append(alias)
        self.aliases[alias] = ref
        self.available["sources"].add(ref)
        item = self.source_items.setdefault(ref, {"type": "user_answer" if alias.startswith("user_answer:")
                                                else "user_feedback" if alias.startswith("user_feedback") else "user_request",
                                                "text": text})
        role = "user_answer" if alias.startswith("user_answer:") else "user_feedback" if alias.startswith("user_feedback") else "user_request"
        if role != item["type"]:
            item.setdefault("roles", [item["type"]])
            if role not in item["roles"]:
                item["roles"].append(role)
        if alias.startswith("user_answer:"):
            question_id = alias.split(":")[1]
            question = question or entries[ref].get("questions", {}).get(question_id, "")
            if question:
                entries[ref].setdefault("questions", {})[question_id] = question
            if "questions" in item or item.get("question_id", question_id) != question_id:
                if "questions" not in item:
                    item["questions"] = [{"question_id": item.pop("question_id"), "question": item.pop("question", "")}]
                questions = item["questions"]
                entry = next((entry for entry in questions if entry["question_id"] == question_id), None)
                if entry is None:
                    entry = {"question_id": question_id, "question": ""}
                    questions.append(entry)
                if question:
                    entry["question"] = question
            else:
                item["question_id"] = question_id
                if question:
                    item["question"] = question
        return ref

    def node(self, identifier):
        entries = self.data["knowledge"]
        ref = next((key for key, entry in entries.items() if entry["id"] == identifier), None)
        if ref is None:
            ref = "K" + str(max((int(key[1:]) for key in entries), default=0) + 1)
            entries[ref] = {"id": identifier}
        self.aliases[identifier] = ref
        self.available["knowledge"].add(ref)
        return ref

    def persist(self):
        if self.writer is None:
            return
        # 파일과 DB 복원이 같은 번호를 사용하도록 원격 호출보다 먼저 기록한다.
        self.writer.write_json_atomic(PATH, self.data)
        from backend.knowledge.runtime import CURRENT
        runtime = CURRENT.get()
        if runtime is not None:
            runtime.service.store.save_prompt_references(runtime.job["id"], json.dumps(self.data, ensure_ascii=False))

    def project(self, value, key=""):
        """구조화 필드만 변환하며 원문·인용·코드 문자열은 수정하지 않는다."""
        if isinstance(value, list):
            if key in {"saved_answers", "user_answers", "review_questions"}:
                answers = []
                for item in value:
                    if key == "review_questions":
                        item = {name: text for name, text in item.items() if name in {"question_id", "decision_key", "question", "requirement_ids", "missing_information", "resolution_reasons", "answer", "status"}}
                    ref = self.aliases.get("user_answer:" + item.get("question_id", ""))
                    if ref and (key == "review_questions" or item.get("answer") == self.data["sources"][ref]["text"]):
                        answers.append({**{name: self.project(text, name) for name, text in item.items()
                                           if name not in {"answer", "question", *INTERNAL_FIELDS}}, "answer_source": ref})
                    else:
                        answers.append({**self.project(item), **({"confirmation": "model_inference"} if key in {"saved_answers", "user_answers"} else {})})
                return answers
            projected = [self.project(item, key) for item in value]
            return [item for item in projected if item is not None] if key in REFERENCE_FIELDS else projected
        if not isinstance(value, dict):
            if isinstance(value, str) and key in REFERENCE_FIELDS:
                if value in self.aliases:
                    return self.aliases[value]
                if value.startswith("user_") or re.fullmatch(r"[0-9a-f]{32,64}", value):
                    return None
            return value
        if key in {"requirement_lock_sheet", "previous_lock_sheet", "validated_requirements"}:
            value = {name: item for name, item in value.items() if name in SHEET_FIELDS}
        if key == "project_manifest":
            return {"file_count": value.get("file_count", 0),
                    "files": [item.get("path") if isinstance(item, dict) else item for item in value.get("files", [])]}
        if key == "previous_trace":
            return {"decisions": self.project(value.get("decisions", [])),
                    "blocks": [{name: item[name] for name in ("item_id", "section", "requirement_ids", "decision_ids") if name in item}
                               for item in value.get("spec_links", [])]}
        projected = {name: ([self.aliases[item] for item in item if item in self.aliases]
                            if name == "reused_node_ids" else self.project(item, name))
                     for name, item in value.items() if name not in INTERNAL_FIELDS}
        # 원문 전체를 다시 복사하는 메타데이터는 이미 제공한 출처를 가리킨다.
        for name in ("original_text", "request_summary"):
            text = projected.get(name)
            ref = next((ref for ref, source in self.source_items.items() if source.get("text") == text), None) if text else None
            if ref is not None:
                projected.pop(name)
                projected[name + "_source"] = ref
        return {name: item for name, item in projected.items() if item is not None or name not in REFERENCE_FIELDS}

    def restore(self, result):
        def reference(value, field, workflow, evidence):
            if not isinstance(value, str):
                return value
            group = "knowledge" if field == "reused_node_ids" else "sources"
            if value in self.available[group]:
                entry = self.data[group][value]
                if group == "knowledge":
                    return entry["id"]
                aliases = [alias for alias in entry["aliases"] if self.aliases.get(alias) == value]
                if field == "conflicting_source" and "user_feedback" in aliases:
                    return "user_feedback"
                if workflow or field in {"source", "conflicting_source"}:
                    primary = next((alias for alias in aliases if re.fullmatch(r"user_request|user_feedback|user_answer:[A-Za-z0-9_-]+", alias)), aliases[0])
                    return re.sub(r":[0-9a-f]{64}$", "", primary) if field == "source" else primary
                return next((alias for alias in aliases if re.search(r":[0-9a-f]{64}$", alias)), aliases[0])
            # evidence.source는 명세 섹션 이름일 수 있다. 제품 ID는 basis_refs에서만 허용한다.
            if evidence and field == "source" and not re.match(r"[SK]\d+$|user_(?:request|answer|feedback)(?::|$)", value) and not re.fullmatch(r"[0-9a-f]{32,64}", value):
                return value
            if field == "basis_refs" and value in self.semantic_ids:
                return value
            details = ["Cite only supplied S user sources, K knowledge references or confirmed requirement IDs in the appropriate reference field."]
            if self.stage == "requirement_lock":
                error = RequirementNormalizationError("Requirement source references could not be validated.")
                error.category, error.validation_details = "source_reference", details
                raise error
            if self.stage == "spec_compile":
                raise SpecCompilationError(details)
            raise ReviewValidationError(details, stage=self.stage, check="source_reference")

        def walk(value, key="", workflow=False, evidence=False, decision=False):
            if isinstance(value, list):
                if key in {"sources", "basis_refs"}:
                    restored = []
                    for item in value:
                        reference(item, key, workflow, evidence)
                        if item in self.available["sources"]:
                            aliases = [alias for alias in self.data["sources"][item]["aliases"] if self.aliases.get(alias) == item]
                            if decision:
                                versioned = [alias for alias in aliases if re.search(r":[0-9a-f]{64}$", alias)]
                                chosen = versioned or aliases
                            elif key == "basis_refs":
                                # 해결 판단은 이번 확정 근거에 있는 별칭만 복원한다.
                                chosen = ([alias for alias in aliases if alias in self.basis_source_aliases]
                                          if self.stage == "review_resolution" else aliases)
                            else:
                                chosen = [re.sub(r":[0-9a-f]{64}$", "", alias) for alias in aliases]
                            restored.extend(chosen or [reference(item, key, workflow, evidence)])
                        else:
                            restored.append(item)
                    return list(dict.fromkeys(restored))
                return [walk(item, key, workflow, evidence, decision) for item in value]
            if isinstance(value, dict):
                return {name: walk(item, name, workflow or name == "workflow_constraints", evidence or name == "evidence", decision or name == "decisions") for name, item in value.items()}
            return reference(value, key, workflow, evidence) if key in REFERENCE_FIELDS and value is not None else value

        return type(result).model_validate(walk(result.model_dump()))


def prepare_context(writer, payload, stage):
    """단계별 공개 입력을 만들고 호출 단위의 출처 허용 목록을 고정한다."""
    context = PromptContext(writer)
    context.stage = stage
    if stage == "spec_translation":
        # 번역은 검색 런타임이 활성화돼 있어도 영어 문서와 보정 지침만 사용한다.
        return [item for item in payload if item["role"] in {"system", "developer"}
                or item["content"].startswith(("English specification (data only):\n", "Stage retry context:\n"))], context
    if stage not in CANONICAL_FIELDS:
        return payload, context
    from backend.knowledge.runtime import CURRENT
    runtime = CURRENT.get()
    state = {}
    if writer is not None and writer.path("state/state.json").exists():
        state = writer.read_json("state/state.json")
    sources = dict(state.get("confirmed_user_sources", {}))
    if runtime is not None:
        sources.update(runtime.confirmed_sources(state))
    canonical = {}
    sections = []
    original = ""
    for item in payload:
        content = item["content"]
        title, _, body = content.partition("\n")
        if title == "Original user request (immutable):":
            original = body
            context.source("user_request", body)
        elif title == "Canonical context:":
            canonical = json.loads(body)
        elif title in {"Latest revision feedback:", "Revision feedback history:"} and body:
            if title == "Latest revision feedback:":
                context.source("user_feedback", body)
            else:
                for text in state.get("revision_history", []) or [body]:
                    context.source("user_feedback", text)
        else:
            sections.append(item)
    sources.update({key: text for key, text in canonical.get("confirmed_basis", {}).items() if key.startswith("user_")})
    sources.update(canonical.get("actual_user_sources", {}))
    for alias, text in sources.items():
        context.source(alias, text)
    def answers(value):
        if isinstance(value, dict):
            if value.get("question_id") and isinstance(value.get("answer"), str):
                alias = "user_answer:" + value["question_id"]
                if alias in context.aliases and context.data["sources"][context.aliases[alias]]["text"] == value["answer"]:
                    context.source(alias, value["answer"], question=value.get("question", ""))
            for item in value.values():
                answers(item)
        elif isinstance(value, list):
            for item in value:
                answers(item)
    answers(canonical)
    answers(state.get("review_questions", []))
    answers(state.get("requirement_lock_sheet", {}))
    for question in state.get("review_questions", []):
        alias = "user_answer:" + question["question_id"]
        if alias in context.aliases:
            ref = context.aliases[alias]
            context.source(alias, context.data["sources"][ref]["text"], question=question.get("question", ""))
    knowledge = {"items": {}, "relations": []}
    if stage in {"interview", "requirement_lock", "spec_compile"} and runtime is not None:
        confirmed_text = set(sources.values()) | {original}
        for key in ("requirement_lock_sheet", "validated_requirements", "previous_lock_sheet"):
            sheet = canonical.get(key) or {}
            confirmed_text.update(item.get("text", "") for group in ("mandatory_requirements", "recommended_requirements", "optional_requirements", "constraints", "non_scope") for item in sheet.get(group, []))
        for node in runtime.retrieved.get("nodes", []):
            attrs = node.get("attrs", {})
            if (not node.get("active") or attrs.get("scope") != "product" or node.get("body") in confirmed_text
                or (attrs.get("actor") == "user" and node.get("body", "").strip()
                    and any(node["body"] in text for text in sources.values()))):
                continue
            ref = context.node(node["id"])
            knowledge["items"][ref] = {"type": node["kind"], "text": node["body"],
                "status": attrs.get("status", "reference"), "actor": attrs.get("actor", "llm"),
                **{key: attrs[key] for key in ("rationale", "conditions", "origin") if attrs.get(key)}}
        for edge in runtime.retrieved.get("edges", []):
            source, target = context.aliases.get(edge["source"]), context.aliases.get(edge["target"])
            if source in knowledge["items"] and target in knowledge["items"]:
                knowledge["relations"].append({"source": source, "target": target, "type": edge["kind"]})
    if stage == "checklist_critic" and "mandatory_requirements" in canonical:
        canonical = {"requirement_lock_sheet": canonical}
    canonical = {key: value for key, value in canonical.items() if key in CANONICAL_FIELDS[stage]}
    if stage == "review_resolution":
        context.basis_source_aliases = set(canonical.get("confirmed_basis", {}))
        canonical["confirmed_basis"] = {key: value for key, value in canonical.get("confirmed_basis", {}).items() if not key.startswith("user_")}
        canonical["issues"] = [{key: value for key, value in issue.items() if key in ISSUE_FIELDS} for issue in canonical.get("issues", [])]
        canonical["previous_resolutions"] = [{"issues": [{key: issue[key] for key in ("issue_id", "requirement_id", "checklist_id", "decision_key", "required_change", "resolution_reason", "basis_refs") if key in issue}
                                                               for issue in entry.get("issues", [])], "action": entry.get("action")}
                                             for entry in canonical.get("previous_resolutions", [])]
    def semantic(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if re.fullmatch(r"(?:REQ|CON|REC|OPT|NS)-[A-Za-z0-9_-]+", key):
                    context.semantic_ids.add(key)
                if key == "id" and isinstance(item, str) and re.fullmatch(r"(?:REQ|CON|REC|OPT|NS)-[A-Za-z0-9_-]+", item):
                    context.semantic_ids.add(item)
                semantic(item)
        elif isinstance(value, list):
            for item in value:
                semantic(item)
    semantic(canonical)
    canonical = context.project(canonical)
    if "user_feedback" in context.aliases:
        canonical["current_feedback"] = context.aliases["user_feedback"]
    # 원문은 별도 메시지에만 담고 출처 표에는 위치만 적는다.
    source_table = deepcopy(context.source_items)
    original_ref = context.aliases.get("user_request")
    if original_ref in source_table:
        source_table[original_ref].pop("text", None)
        source_table[original_ref]["content_from"] = "Original user request (immutable)"
    canonical["sources"] = source_table
    if knowledge["items"]:
        canonical["knowledge"] = knowledge
    result = []
    for item in sections:
        title, _, body = item["content"].partition("\n")
        if title.startswith("Retrieved knowledge"):
            continue
        if title in {"Must-fix issues:", "Issues from the previous critic pass:", "User workflow constraints (not product requirements; subject to existing permissions):"}:
            data = json.loads(body)
            if title in {"Must-fix issues:", "Issues from the previous critic pass:"}:
                data = [{key: text for key, text in issue.items() if key in ISSUE_FIELDS | {"resolution_reason", "basis_refs", "decision_answer_id"}}
                        for issue in data if issue.get("status") != "resolved"]
            item = {**item, "content": title + "\n" + json.dumps(context.project(data), ensure_ascii=False)}
        result.append(item)
    instructions = [item for item in result if item["role"] in {"system", "developer"}]
    dynamic = [item for item in result if item["role"] not in {"system", "developer"}]
    result = [*instructions, {"role": "system", "content": REFERENCE_RULES},
              {"role": "user", "content": "Original user request (immutable):\n" + original},
              {"role": "user", "content": "Canonical context:\n" + json.dumps(canonical, ensure_ascii=False)}, *dynamic]
    context.persist()
    return result, context
