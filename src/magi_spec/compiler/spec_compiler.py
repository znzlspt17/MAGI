"""v2 Spec Compiler — generates the final agent specification from a RequirementLockSheet."""

from __future__ import annotations

import json
from typing import Any

from magi_spec.core.config import MagiConfig
from magi_spec.core.evidence import EvidenceRegistry
from magi_spec.core.prompts import load_prompt
from magi_spec.core.provider_output import extract_json_object
from magi_spec.providers.base import ProviderFactory
from magi_spec.schemas.issue_packet import IssuePacket
from magi_spec.schemas.provider_packets import choose_spec_markdown
from magi_spec.schemas.requirement_lock import RequirementLockSheet
from magi_spec.skills.registry import SkillRegistry


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


class SpecCompiler:
    """v2 spec compiler. Routes through 'compiler' key in model_routing."""

    agent_id = "compiler"

    def __init__(
        self,
        *,
        config: MagiConfig,
        providers: ProviderFactory,
        skills: SkillRegistry,
        evidence: EvidenceRegistry,
    ) -> None:
        self.config = config
        self.providers = providers
        self.skills = skills
        self.evidence = evidence

    def compile(
        self,
        sheet: RequirementLockSheet,
        manifest: dict[str, Any] | None,
        issues: list[IssuePacket] | None = None,
    ) -> str:
        """Compile a single English Markdown specification from the lock sheet."""
        self.skills.assert_allowed(self.agent_id, "compose_final_spec")
        fallback = self._fallback_spec(sheet, manifest)
        route = self.config.model_routing[self.agent_id]
        provider = self.providers.get(route.provider)
        raw_output = provider.complete(
            [{"role": "user", "content": self._build_prompt(sheet, manifest, issues)}],
            model=route.model,
            temperature=0,
        )
        parsed = extract_json_object(raw_output)
        candidate = choose_spec_markdown(parsed, raw_output=raw_output, fallback=fallback)
        if self.english_only(candidate) and self.has_required_headings(candidate):
            return candidate
        return fallback

    # ── prompt ───────────────────────────────────────────────────────────────

    def _build_prompt(
        self,
        sheet: RequirementLockSheet,
        manifest: dict[str, Any] | None,
        issues: list[IssuePacket] | None,
    ) -> str:
        manifest_summary = {
            "root": (manifest or {}).get("root"),
            "file_count": (manifest or {}).get("file_count", 0),
            "files": [
                item.get("path")
                for item in (manifest or {}).get("files", [])[:50]
            ],
        }
        must_fix_section = ""
        if issues:
            blocking = [
                i for i in issues
                if i.blocking and i.status != "resolved"
            ]
            if blocking:
                must_fix_section = "\n\nMUST FIX (blocking issues from previous critic pass):\n" + "\n".join(
                    f"- [{i.checklist_id}] {i.required_change}" for i in blocking
                )

        parts = [
            load_prompt("compiler"),
            "Requirement Lock Sheet:",
            json.dumps(sheet.to_dict(), ensure_ascii=False, indent=2),
            "Project manifest summary:",
            json.dumps(manifest_summary, ensure_ascii=False, indent=2),
        ]
        if must_fix_section:
            parts.append(must_fix_section)
        parts += [
            "Return only JSON with key spec_markdown. The value must be English-only Markdown.",
            "The spec_markdown must include every required heading in order: "
            + "; ".join(REQUIRED_FINAL_SPEC_HEADINGS),
        ]
        return "\n\n".join(parts)

    # ── fallback spec ─────────────────────────────────────────────────────────

    def _fallback_spec(
        self,
        sheet: RequirementLockSheet,
        manifest: dict[str, Any] | None,
    ) -> str:
        request = sheet.request_summary or ""
        if not request or not self.english_only(request):
            request = "The original request is preserved in `raw/user_request.md`."

        project_summary = "No project folder was provided."
        if manifest:
            project_summary = (
                f"Project folder `{manifest.get('root')}` was scanned read-only. "
                f"{manifest.get('file_count', 0)} files were included."
            )

        mandatory_lines = [
            f"- {r.text}"
            for r in sheet.mandatory_requirements
            if self.english_only(r.text)
        ] or ["- Satisfy the user's original request."]

        non_scope_lines = [
            f"- {r.text}"
            for r in sheet.non_scope
            if self.english_only(r.text)
        ] or [
            "- Do not add unrelated product features.",
            "- Do not deploy services or modify external systems unless explicitly required.",
        ]

        evidence_items = self.evidence.to_dict()["items"]
        evidence_lines = [self._evidence_line(item) for item in evidence_items[:12]] or [
            "- No evidence was recorded."
        ]

        return "\n".join([
            "# Final Agent Specification",
            "",
            "## 1. Mission",
            "Build the software requested by the user while preserving every explicit constraint in this specification.",
            "",
            "## 2. Background",
            "This specification was generated by MAGI Spec Engine v2 after intent analysis, requirement locking, and checklist review.",
            project_summary,
            "",
            "## 3. User Intent",
            request,
            "",
            "## 4. Scope",
            "### 4.1 In Scope",
            "- Implement only the behavior explicitly requested by the user and classified as Mandatory or Recommended.",
            "- Preserve the existing project architecture unless this specification explicitly directs a change.",
            "",
            "### 4.2 Out of Scope",
            *non_scope_lines,
            "",
            "## 5. Definitions",
            "- Mandatory: required for acceptance.",
            "- Recommended: valuable but not allowed to override mandatory constraints.",
            "- Optional: may be implemented only after mandatory and recommended work is complete.",
            "- Out of Scope: must not be implemented.",
            "",
            "## 6. Evidence Summary",
            *evidence_lines,
            "",
            "## 7. Mandatory Requirements",
            *mandatory_lines,
            "",
            "## 8. Recommended Requirements",
            "- Follow existing repository conventions, naming, and dependency patterns.",
            "- Prefer small, focused modules over broad mixed-responsibility code.",
            "",
            "## 9. Optional Requirements",
            "- Add extra examples only when they clarify the requested behavior without expanding scope.",
            "",
            "## 10. Forbidden Behaviors",
            "- Do not implement unrelated features.",
            "- Do not ignore user constraints.",
            "- Do not hide unresolved blockers.",
            "- Do not rely on model identity or routing authority as a reason for implementation decisions.",
            "",
            "## 11. Input Contract",
            "Accept the inputs described by the user's request. Validate unsupported inputs with clear errors.",
            "",
            "## 12. Output Contract",
            "Produce the outputs described by the user's request. Avoid undocumented side effects.",
            "",
            "## 13. Architecture",
            "Use the repository's existing architecture as the default. Add new boundaries only when they reduce complexity or enforce a required contract.",
            "",
            "## 14. Module Responsibilities",
            "- Keep CLI or UI code thin.",
            "- Put reusable business logic in package modules.",
            "- Keep persistence, configuration, and external integrations behind explicit interfaces.",
            "",
            "## 15. Data Flow",
            "Input should be validated, transformed through explicit domain logic, persisted or emitted through documented outputs, and verified by tests.",
            "",
            "## 16. Error Handling Policy",
            "Raise actionable errors for missing inputs, invalid configuration, unsupported files, failed writes, and unsafe operations.",
            "",
            "## 17. Configuration Policy",
            "Use explicit configuration for behavior that differs by environment. Do not hard-code credentials.",
            "",
            "## 18. Persistence / Artifact Policy",
            "Persist user-facing outputs only where requested. Do not mutate unrelated project files.",
            "",
            "## 19. Implementation Order",
            "1. Inspect the existing project structure.",
            "2. Implement the narrowest complete change.",
            "3. Add or update focused tests.",
            "4. Run verification commands and report any commands that could not be run.",
            "",
            "## 20. Acceptance Criteria",
            "- The requested behavior is implemented.",
            "- Existing behavior outside the request remains intact.",
            "- Tests cover the changed behavior.",
            "- Any assumptions or skipped verification steps are reported.",
            "",
            "## 21. Test Plan",
            "- Add unit tests for new domain behavior.",
            "- Add CLI or integration tests when user-visible workflows change.",
            "- Run the relevant existing test suite.",
            "",
            "## 22. Manual Verification Checklist",
            "- Confirm the main user workflow works end to end.",
            "- Confirm errors are readable and actionable.",
            "- Confirm generated or modified files are in the expected locations.",
            "",
            "## 23. Instructions for AI Coding Agent",
            "Implement the requested project changes only. Do not broaden scope, do not skip tests, and do not treat this instruction document as permission to modify unrelated systems.",
            "",
        ])

    # ── static helpers (shared contract) ─────────────────────────────────────

    @staticmethod
    def english_only(text: str) -> bool:
        return not any("\uac00" <= ch <= "\ud7a3" for ch in text)

    @staticmethod
    def has_required_headings(text: str) -> bool:
        return all(h in text for h in REQUIRED_FINAL_SPEC_HEADINGS)

    @classmethod
    def _evidence_line(cls, item: dict[str, Any]) -> str:
        summary = str(item.get("summary", ""))
        if not cls.english_only(summary):
            summary = "Non-English evidence summary is preserved in the evidence registry."
        return f"- {item.get('evidence_id')}: {item.get('evidence_type')} - {summary}"
