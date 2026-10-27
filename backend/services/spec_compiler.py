"""v2 Spec Compiler — generates the final agent specification from a RequirementLockSheet."""

from __future__ import annotations

import json
import re
from typing import Any

from backend.config import Config
from backend.errors import SpecCompilationError
from backend.infrastructure.stage_retry import CURRENT_RETRY, attempt_limit
from backend.infrastructure.output_language import OutputLanguageError
from backend.knowledge.core import Documents
from backend.infrastructure.prompt_messages import messages as build_messages
from backend.infrastructure.provider_call import complete_with_usage
from backend.infrastructure.prompts import load_prompt
from backend.models import SpecResponse, SpecDraftResponse, assemble_spec_draft
from backend.models import IssuePacket
from backend.models import RequirementLockSheet
from backend.providers.llm_provider import ChatModelProvider
from backend.services.skill_registry import SkillRegistry


REQUIRED_FINAL_SPEC_HEADINGS = [
    "# Final Agent Specification",
    "## 1. Mission",
    "## 2. Background",
    "## 3. User Intent",
    "## 4. Scope",
    "### 4.1 In Scope",
    "### 4.2 Out of Scope",
    "## 5. Definitions",
    "## 6. Evidence Summary",
    "## 7. Mandatory Requirements",
    "## 8. Recommended Requirements",
    "## 9. Optional Requirements",
    "## 10. Forbidden Behaviors",
    "## 11. Input Contract",
    "## 12. Output Contract",
    "## 13. Architecture",
    "## 14. Module Responsibilities",
    "## 15. Data Flow",
    "## 16. Error Handling Policy",
    "## 17. Configuration Policy",
    "## 18. Persistence / Artifact Policy",
    "## 19. Implementation Order",
    "## 20. Acceptance Criteria",
    "## 21. Test Plan",
    "## 22. Manual Verification Checklist",
    "## 23. Instructions for AI Coding Agent",
]

_SECTION_7_HEADING = re.compile(r"(?m)^## 7\. Mandatory Requirements\s*$")
_TOP_LEVEL_HEADING = re.compile(r"(?m)^## (?!#)")


class SpecCompiler:
    """v2 spec compiler. Routes through 'compiler' key in model_routing."""

    agent_id = "compiler"

    def __init__(
        self,
        *,
        config: Config,
        provider: ChatModelProvider,
        skills: SkillRegistry,
    ) -> None:
        self.config = config
        self.provider = provider
        self.skills = skills

    def compile(
        self,
        sheet: RequirementLockSheet,
        manifest: dict[str, Any] | None,
        issues: list[IssuePacket] | None = None,
        *,
        user_request: str = "",
        previous_spec: str = "",
        revision_feedback: str = "",
        revision_history: list[str] | None = None,
        writer: Documents,
    ) -> str:
        """검증 진단을 단계의 공통 재시도 예산으로 전달한다."""
        sheet.require_validated()
        error = None
        limit = attempt_limit()
        for attempt in range(limit):
            context = CURRENT_RETRY.get()
            token = CURRENT_RETRY.set(context or {"attempt": attempt, "error": error})
            try:
                return self._compile_once(sheet, manifest, issues, user_request=user_request,
                    previous_spec=previous_spec, revision_feedback=revision_feedback,
                    revision_history=revision_history, writer=writer)
            except (SpecCompilationError, OutputLanguageError) as exc:
                error = exc
                writer.write_json("analysis/spec_compile_validation.json", {
                    "stage": "spec_compile", "attempt": (context or {"attempt": attempt})["attempt"] + 1,
                    "validation_details": exc.validation_details,
                    "failed_checks": getattr(exc, "failed_checks", []),
                    "phase": getattr(exc, "validation_phase", "trace"),
                    "location": getattr(exc, "validation_location", None),
                }, overwrite=True)
                if attempt + 1 == limit:
                    raise
            finally:
                CURRENT_RETRY.reset(token)
        raise AssertionError("Unreachable compiler validation retry")

    def _compile_once(
        self,
        sheet: RequirementLockSheet,
        manifest: dict[str, Any] | None,
        issues: list[IssuePacket] | None = None,
        *,
        user_request: str = "",
        previous_spec: str = "",
        revision_feedback: str = "",
        revision_history: list[str] | None = None,
        writer: Documents,
    ) -> str:
        """Compile a single English Markdown specification from the lock sheet."""
        self.skills.assert_allowed(self.agent_id, "compose_final_spec")
        route = self.config.model_routing[self.agent_id]
        provider = self.provider
        previous_trace = {}
        if writer.exists("analysis/spec_trace.json"):
            previous_trace = writer.read_json("analysis/spec_trace.json")
        runtime = writer.runtime
        if runtime is not None:
            previous_trace["decisions"] = runtime.bind_decisions(previous_trace.get("decisions", []), previous_trace.get("decisions", []))
        messages = self._build_messages(
            sheet,
            manifest,
            issues,
            user_request=user_request,
            previous_spec=previous_spec,
            revision_feedback=revision_feedback,
            revision_history=revision_history or [],
            previous_trace=previous_trace,
        )
        raw_output = complete_with_usage(
            writer, provider, messages, model=route.model, stage="spec_compile", temperature=0,
        )
        if not isinstance(raw_output, SpecDraftResponse):
            raise SpecCompilationError(["Return the complete structured SpecDraftResponse."])
        from backend.services.implementation_plan import prepare_plan
        task_plan = prepare_plan(raw_output, sheet)
        draft_blocks = [{"section": name, **block.model_dump()} for name in type(raw_output).model_fields
                        if name != "decisions" for block in getattr(raw_output, name)]
        draft_blocks = [b for b in draft_blocks if b["section"] != "implementation_order"] + [
            {"section": "implementation_order", **t, "text": t["rendered"]} for t in task_plan["tasks"]]
        raw_output = assemble_spec_draft(raw_output, sheet, task_plan)
        from backend.knowledge.trace import validate_decisions, validate_links
        runtime = writer.runtime
        decisions = [item.model_dump() for item in raw_output.decisions]
        if runtime is not None:
            decisions = runtime.bind_decisions(decisions, previous_trace.get("decisions", []))
        links = [item.model_dump() for item in raw_output.spec_links]
        if runtime is not None and not links:
            raise SpecCompilationError(["spec_links: include implementation links covering all mandatory requirement IDs."], check="spec_links")
        if runtime is not None and not {item.id for item in sheet.mandatory_requirements} <= {
            req for link in links for req in link["requirement_ids"]
        }:
            raise SpecCompilationError(["spec_links.requirement_ids: cover every mandatory requirement ID in the supplied lock sheet."], check="spec_links")
        retrieved = runtime.reusable_ids() if runtime else []
        _validate_trace(validate_decisions, decisions, sheet.to_dict(), retrieved, revision_feedback, user_request,
                           runtime.confirmed_sources({"user_request": user_request, "revision_feedback": revision_feedback}) if runtime else None,
                           previous_trace.get("decisions", []), writer.state.get("reused_decisions", []))
        if {item["id"] for item in decisions} & {item["id"] for item in sheet.decisions}:
            raise SpecCompilationError(["decisions: reference existing lock decision IDs in spec_links without redeclaring them."], check="decision_trace")
        links = _anchor_links(links, raw_output.model_dump(), "response")
        _validate_trace(validate_links, links, sheet.decisions + decisions, sheet.to_dict(), raw_output.model_dump())
        from backend.services.workflow_constraints import validate_product_boundary
        try:
            validate_product_boundary(sheet, [raw_output.markdown(), json.dumps(decisions, ensure_ascii=False)])
        except ValueError:
            raise SpecCompilationError(["Product specification and decision traces must exclude workflow instructions and WF-* references."], check="product_boundary") from None
        candidate = raw_output.markdown()
        if self.has_required_headings(candidate):
            assembled = _assemble_locked_sections(candidate, sheet)
            if self.english_only(assembled):
                rendered = _rendered_sections(assembled)
                links = _anchor_links(links, rendered, "assembled")
                _validate_trace(validate_links, links, sheet.decisions + decisions, sheet.to_dict(), rendered)
                writer.write_json("analysis/spec_trace.json", {"decisions": decisions, "links": links}, overwrite=True)
                from backend.services.change_review import BLOCKS, digest, normalize
                if task_plan:
                    from backend.services.implementation_plan import PATH
                    writer.write_json(PATH, {**task_plan, "source_hash": digest(normalize(assembled))}, overwrite=True)
                writer.write_json(BLOCKS, {"source_hash": digest(normalize(assembled)),
                    "blocks": draft_blocks}, overwrite=True)
                return assembled
        raise SpecCompilationError(["Return all required English section bodies in the supplied schema."], check="spec_structure")

    # ── prompt ───────────────────────────────────────────────────────────────

    def _build_messages(
        self,
        sheet: RequirementLockSheet,
        manifest: dict[str, Any] | None,
        issues: list[IssuePacket] | None,
        *,
        user_request: str,
        previous_spec: str,
        revision_feedback: str,
        revision_history: list[str],
        previous_trace: dict | None = None,
    ) -> list[dict[str, str]]:
        product_sheet = sheet.to_dict()
        workflow = product_sheet.pop("workflow_constraints")
        manifest_summary = {
            "root": (manifest or {}).get("root"),
            "file_count": (manifest or {}).get("file_count", 0),
            "files": [item.get("path") for item in (manifest or {}).get("files", [])],
            "requirement_lock_sheet": product_sheet,
            "previous_trace": previous_trace or {},
        }
        required = [
            issue.to_dict()
            for issue in issues or []
            if issue.severity in {"blocking", "major"} and issue.status != "resolved"
        ]
        history = "\n\n".join(item for item in revision_history if item.strip())
        return build_messages(
            load_prompt("compiler"),
            user_request,
            json.dumps(manifest_summary, ensure_ascii=False, indent=2),
            ("Must-fix issues", json.dumps(required, ensure_ascii=False, indent=2)),
            ("Revision feedback history", history),
            ("Latest revision feedback", revision_feedback),
            ("Current draft to preserve and revise", previous_spec),
            workflow_constraints=workflow,
        )


    # ── static helpers (shared contract) ─────────────────────────────────────

    @staticmethod
    def english_only(text: str) -> bool:
        from backend.infrastructure.output_language import prose, has_hangul
        return not has_hangul(prose(text))

    @staticmethod
    def has_required_headings(text: str) -> bool:
        visible_text = _mask_fenced_code(text)
        positions = [_heading_position(visible_text, heading) for heading in REQUIRED_FINAL_SPEC_HEADINGS]
        return all(position is not None for position in positions) and positions == sorted(positions)


def _rendered_sections(spec: str) -> dict[str, str]:
    """잠금 섹션을 조립한 최종 문서에서 응답 필드별 실제 본문을 복원한다."""
    fields = [name for name in SpecResponse.model_fields if name not in {"decisions", "spec_links"}]
    headings = [heading for heading in REQUIRED_FINAL_SPEC_HEADINGS if heading not in {
        "# Final Agent Specification", "## 4. Scope", "## 7. Mandatory Requirements"}]
    visible = _mask_fenced_code(spec)
    sections = {}
    for name, heading in zip(fields, headings):
        match = re.search(rf"(?m)^{re.escape(heading)}[ \t]*$", visible)
        if match is None:
            continue
        level = len(heading.split(" ", 1)[0])
        # 사용자 본문의 임의 heading이 아니라 다음 고정 명세 heading까지 보존한다.
        positions = [found.start() for boundary in REQUIRED_FINAL_SPEC_HEADINGS
                     if len(boundary.split(" ", 1)[0]) <= level
                     for found in re.finditer(rf"(?m)^{re.escape(boundary)}[ \t]*$", visible)
                     if found.start() > match.start()]
        end = min(positions) if positions else len(spec)
        sections[name] = spec[match.end():end]
    return sections


def _replace_locked_body(candidate: str, heading: str, body: str) -> str:
    """동일하거나 상위 수준의 다음 heading 전까지 잠금 본문을 교체한다."""
    visible = _mask_fenced_code(candidate)
    match = re.search(rf"(?m)^{re.escape(heading)}[ \t]*$", visible)
    if match is None:
        return candidate
    level = len(heading.split(" ", 1)[0])
    following = re.search(rf"(?m)^#{{1,{level}}} ", visible[match.end():])
    end = match.end() + following.start() if following else len(candidate)
    return candidate[:match.end()].rstrip() + "\n\n" + body + "\n\n" + candidate[end:]


def _assemble_locked_sections(candidate: str, sheet: RequirementLockSheet) -> str:
    candidate = _assemble_locked_mandatory_section(candidate, sheet)
    candidate = _replace_locked_body(candidate, "### 4.2 Out of Scope", "\n".join(
        f"- [{item.id}] {item.text}" for item in sheet.non_scope
    ) or "No explicit product exclusions were supplied.")
    if sheet.constraints:
        # 다른 섹션의 동명 heading을 제약조건으로 오인하지 않는다.
        visible = _mask_fenced_code(candidate)
        parent = re.search(r"(?m)^## 10\. Forbidden Behaviors[ \t]*$", visible)
        if parent:
            following = _TOP_LEVEL_HEADING.search(visible, parent.end())
            end = following.start() if following else len(candidate)
            section = candidate[parent.start():end]
            body = "Violating any of the following locked constraints is forbidden.\n\n" + "\n".join(
                f"- [{item.id}] {item.text}" for item in sheet.constraints
            )
            if re.search(r"(?m)^### Locked Constraints[ \t]*$", _mask_fenced_code(section)):
                section = _replace_locked_body(section, "### Locked Constraints", body)
            else:
                section = section.rstrip() + "\n\n### Locked Constraints\n\n" + body + "\n\n"
            candidate = candidate[:parent.start()] + section + candidate[end:]
    return candidate


def _assemble_locked_mandatory_section(
    candidate: str,
    sheet: RequirementLockSheet,
) -> str:
    """Replace only section 7 with the verified lock wording and identifiers."""
    visible_candidate = _mask_fenced_code(candidate)
    heading = _SECTION_7_HEADING.search(visible_candidate)
    if heading is None:
        return candidate
    following = _TOP_LEVEL_HEADING.search(visible_candidate, heading.end())
    section_end = following.start() if following is not None else len(candidate)
    locked_lines = [
        f"- [{item.id}] {item.text}"
        for item in sheet.mandatory_requirements
        if item.id.strip() and item.text.strip()
    ]
    if not locked_lines:
        return candidate
    replacement = f"{candidate[:heading.end()].rstrip()}\n\n"
    replacement += "\n".join(locked_lines)
    replacement += "\n\n"
    return replacement + candidate[section_end:]


def _mask_fenced_code(text: str) -> str:
    """코드 예시 안의 heading과 비영어 문자열은 명세 본문 검사에서 제외한다."""
    masked: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence is None and marker:
            fence = marker.group(1)
            masked.append("".join("\n" if char == "\n" else " " for char in line))
        elif fence is not None:
            masked.append("".join("\n" if char == "\n" else " " for char in line))
            if _is_fence_close(line, fence):
                fence = None
        else:
            masked.append(line)
    return "".join(masked)


def _heading_position(text: str, heading: str) -> int | None:
    match = re.search(rf"(?m)^{re.escape(heading)}\s*$", text)
    return match.start() if match is not None else None


def _is_fence_close(line: str, opening: str) -> bool:
    marker = re.match(r"^ {0,3}(`+|~+)[ \t]*(?:\r?\n)?$", line)
    return bool(
        marker
        and marker.group(1)[0] == opening[0]
        and len(marker.group(1)) >= len(opening)
    )


def _validate_trace(validator, *args):
    """원응답과 외부 예외 원문은 진단이나 재시도에 포함하지 않는다."""
    try:
        validator(*args)
    except ValueError as exc:
        raise SpecCompilationError(getattr(exc, "validation_details", [
            "decisions: use valid unique IDs, known requirement/source references, and verified user provenance."
        ]), check="spec_links" if validator.__name__ == "validate_links" else "decision_trace") from None


def _anchor_links(links, sections, phase):
    """공백만 다른 인용을 유일한 실제 원문 범위에 연결한다. 의미 유사도는 사용하지 않는다."""
    anchored = []
    for index, raw in enumerate(links):
        link = dict(raw)
        text = sections.get(link["section"])
        quote = link["quote"]
        if not isinstance(text, str) or not quote.strip() or quote in text:
            anchored.append(link)
            continue
        # 비공백 문자의 대소문자·기호·순서는 모두 그대로 일치해야 한다.
        tokens = re.findall(r"\S+", quote)
        pattern = r"\s+".join(re.escape(token) for token in tokens)
        matches = list(re.finditer(pattern, text))
        if len(matches) == 1:
            link["quote"] = matches[0].group()
        else:
            error = SpecCompilationError([
                f"spec_links[{index}].quote: {phase} validation failed; copy a short exact contiguous quote "
                "from the named section, without paraphrasing, added Markdown, or omitted text. "
                "For sections replaced by locked content, link to an implementation section instead."
            ], check="quote_anchor")
            error.validation_phase = phase
            error.validation_location = {"index": index, "field": "quote",
                "section": link["section"] if link["section"] in SpecResponse.model_fields else "unknown",
                "quote_length": len(quote), "section_length": len(text),
                "whitespace_matches": len(matches)}
            raise error
        anchored.append(link)
    return anchored
