"""LangGraph node implementations — v2 SpecForge pipeline only."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from magi_spec.compiler.requirement_lock import RequirementLockBuilder
from magi_spec.compiler.spec_compiler import SpecCompiler
from magi_spec.core.artifacts import ArtifactWriter
from magi_spec.core.config import MagiConfig
from magi_spec.core.evidence import EvidenceRegistry
from magi_spec.core.prompts import load_prompt
from magi_spec.core.state import (
    STATUS_ANALYZING,
    STATUS_COMPILING,
    STATUS_CRITIQUING,
    STATUS_CRITICAL_BLOCKED,
    STATUS_NEEDS_USER_INPUT,
    STATUS_PASS_PENDING_USER_APPROVAL,
    STATUS_RESEARCHING,
    WorkflowState,
)
from magi_spec.critic.checklist_critic import ChecklistCritic
from magi_spec.critic.critical_reporter import CriticalReporter
from magi_spec.interview.interviewer import SpecInterviewer
from magi_spec.providers.base import ProviderFactory
from magi_spec.schemas.issue_packet import count_unresolved_blocking, parse_issue_list
from magi_spec.schemas.requirement_lock import RequirementLockSheet
from magi_spec.skills.command_execution import (
    append_guarded_command_result,
    execute_command_guarded,
)
from magi_spec.skills.project_scan import scan_project_folder, summarize_project_context
from magi_spec.skills.registry import SkillRegistry
from magi_spec.skills.web_search import should_research, summarize_web_research, web_search


class WorkflowNodes:
    def __init__(
        self,
        *,
        writer: ArtifactWriter,
        config: MagiConfig,
        providers: ProviderFactory,
        skills: SkillRegistry,
        evidence: EvidenceRegistry,
    ) -> None:
        self.writer = writer
        self.config = config
        self.providers = providers
        self.skills = skills
        self.evidence = evidence
        self._interviewer = SpecInterviewer()
        self._lock_builder = RequirementLockBuilder()
        self._compiler = SpecCompiler(
            config=config, providers=providers, skills=skills, evidence=evidence
        )
        self._critic = ChecklistCritic()
        self._critical_reporter = CriticalReporter(
            config=config, providers=providers, skills=skills, evidence=evidence
        )

    # ── shared infrastructure nodes ─────────────────────────────────────────

    def project_context(self, state: WorkflowState) -> dict[str, Any]:
        project_dir = state.get("project_dir")
        created = list(state.get("created_artifacts", []))
        if project_dir:
            manifest = scan_project_folder(project_dir)
            summary = summarize_project_context(manifest)
            self.evidence.add(
                "PROJECT_FILE",
                "Project folder manifest was collected read-only.",
                str(Path(project_dir).resolve()),
                metadata={"file_count": manifest["file_count"]},
            )
        else:
            manifest = {
                "root": None,
                "file_count": 0,
                "files": [],
                "ignored_directories": [],
                "ignored_secret_patterns": [],
            }
            summary = "# 프로젝트 컨텍스트 요약\n\n- 프로젝트 폴더가 제공되지 않았습니다.\n"

        self.writer.write_json("context/project_manifest.json", manifest)
        self.writer.write_text("context/project_summary.ko.md", summary)
        created.extend(["context/project_manifest.json", "context/project_summary.ko.md"])
        return {
            "project_manifest_path": str(self.writer.path("context/project_manifest.json")),
            "created_artifacts": created,
        }

    def web_research(self, state: WorkflowState) -> dict[str, Any]:
        created = list(state.get("created_artifacts", []))
        mode = state.get("web_search_mode", "auto")
        sources: list[dict[str, Any]] = []
        if should_research(state.get("user_request", ""), mode):
            try:
                sources = web_search(state.get("user_request", ""), max_results=5)
            except Exception:
                if mode == "on":
                    raise
                sources = []
        for source in sources:
            self.evidence.add(
                "WEB_SOURCE",
                source.get("title", "Web source"),
                source.get("url", ""),
                metadata={"query": source.get("query", "")},
            )
        self.writer.write_json("research/web_sources.json", {"sources": sources})
        self.writer.write_text(
            "research/web_research_summary.ko.md", summarize_web_research(sources, mode)
        )
        created.extend(["research/web_sources.json", "research/web_research_summary.ko.md"])
        return {
            "status": STATUS_RESEARCHING,
            "web_sources_path": str(self.writer.path("research/web_sources.json")),
            "created_artifacts": created,
        }

    # ── v2 SpecForge pipeline nodes ──────────────────────────────────────────

    def interview(self, state: WorkflowState) -> dict[str, Any]:
        """Classify request type and identify blocking questions."""
        created = list(state.get("created_artifacts", []))
        manifest: dict[str, Any] = {}
        try:
            manifest = self.writer.read_json("context/project_manifest.json")
        except Exception:
            pass

        route = self.config.model_routing[self._interviewer.agent_id]
        provider = self.providers.get(route.provider)

        def _complete(prompt: str) -> str:
            return provider.complete(
                [{"role": "user", "content": prompt}],
                model=route.model,
                temperature=0,
            )

        result = self._interviewer.run(state, manifest, provider_complete_fn=_complete)

        assumption_doc = (
            "# 초기 가정\n\n"
            + "\n".join(f"- {a}" for a in result.assumptions)
            + "\n"
        )
        question_doc = "# 차단 질문\n\n" + (
            "\n".join(f"- {q}" for q in result.blocking_questions)
            if result.blocking_questions
            else "- 없음\n"
        )

        analysis_files = {
            "analysis/01_intent_parse.ko.md": f"# 의도 분석\n\n요청 유형: {result.request_type}\n",
            "analysis/03_scope_classification.ko.md": (
                "# 범위 분류\n\n- v2 파이프라인: Requirement Lock Sheet에서 관리됩니다.\n"
            ),
            "analysis/04_initial_assumptions.ko.md": assumption_doc,
            "analysis/05_blocking_questions.ko.md": question_doc,
        }
        for path, content in analysis_files.items():
            self.writer.write_text(path, content)
            created.append(path)

        for assumption in result.assumptions:
            self.evidence.add("AGENT_ASSUMPTION", assumption, "interview")

        return {
            "status": STATUS_ANALYZING,
            "request_type": result.request_type,
            "assumptions": result.assumptions,
            "blocking_questions": result.blocking_questions,
            "_interview_direction_changing": result.direction_changing_pending,
            "created_artifacts": created,
        }

    def await_user(self, state: WorkflowState) -> dict[str, Any]:
        """Terminal node: pipeline paused, awaiting user answers."""
        return {"status": STATUS_NEEDS_USER_INPUT}

    def requirement_lock_stage(self, state: WorkflowState) -> dict[str, Any]:
        """Build RequirementLockSheet from interview result."""
        created = list(state.get("created_artifacts", []))
        manifest: dict[str, Any] = {}
        try:
            manifest = self.writer.read_json("context/project_manifest.json")
        except Exception:
            pass

        route = self.config.model_routing[self._lock_builder.agent_id]
        provider = self.providers.get(route.provider)

        def _complete(prompt: str) -> str:
            return provider.complete(
                [{"role": "user", "content": prompt}],
                model=route.model,
                temperature=0,
            )

        from magi_spec.interview.interviewer import InterviewResult
        interview = InterviewResult(
            request_type=state.get("request_type", "feature"),
            blocking_questions=list(state.get("blocking_questions", [])),
            assumptions=list(state.get("assumptions", [])),
        )

        sheet = self._lock_builder.build(
            state, manifest, interview, provider_complete_fn=_complete
        )

        self.writer.write_json("analysis/requirement_lock_sheet.json", sheet.to_dict())
        self.writer.write_text("analysis/requirement_lock_sheet.ko.md", sheet.to_markdown())
        # Compatibility alias
        self.writer.write_text("analysis/02_requirement_lock.ko.md", sheet.to_markdown())
        created.extend([
            "analysis/requirement_lock_sheet.json",
            "analysis/requirement_lock_sheet.ko.md",
            "analysis/02_requirement_lock.ko.md",
        ])

        return {
            "status": STATUS_ANALYZING,
            "requirement_lock": sheet.to_markdown(),
            "requirement_lock_sheet": sheet.to_dict(),
            "created_artifacts": created,
        }

    def spec_compile(self, state: WorkflowState) -> dict[str, Any]:
        """Compile a single English specification from the lock sheet."""
        created = list(state.get("created_artifacts", []))
        manifest: dict[str, Any] = {}
        try:
            manifest = self.writer.read_json("context/project_manifest.json")
        except Exception:
            pass

        sheet_dict = state.get("requirement_lock_sheet")
        sheet = (
            RequirementLockSheet.from_dict(sheet_dict)
            if sheet_dict
            else RequirementLockSheet.build_fallback(
                request_type=state.get("request_type", "feature"),
                request_summary=state.get("user_request", "")[:200],
            )
        )

        issues_raw = state.get("structured_issues", [])
        issues = parse_issue_list({"issues": issues_raw}) if issues_raw else None

        spec = self._compiler.compile(sheet, manifest, issues)
        path = "draft/approval_candidate_spec.en.md"
        self.writer.write_text(path, spec, overwrite=True)
        if path not in created:
            created.append(path)

        return {
            "status": STATUS_COMPILING,
            "approval_candidate_spec": str(self.writer.path(path)),
            "created_artifacts": created,
        }

    def checklist_critic_node(self, state: WorkflowState) -> dict[str, Any]:
        """Run checklist critic on the compiled draft spec."""
        created = list(state.get("created_artifacts", []))

        spec_path = state.get("approval_candidate_spec", "")
        try:
            spec_md = Path(spec_path).read_text(encoding="utf-8") if spec_path else ""
        except Exception:
            spec_md = ""
        if not spec_md:
            try:
                spec_md = self.writer.read_text("draft/approval_candidate_spec.en.md")
            except Exception:
                spec_md = ""

        sheet_dict = state.get("requirement_lock_sheet")
        sheet = (
            RequirementLockSheet.from_dict(sheet_dict)
            if sheet_dict
            else RequirementLockSheet.build_fallback()
        )

        route = self.config.model_routing[self._critic.agent_id]
        provider = self.providers.get(route.provider)

        def _complete(prompt: str) -> str:
            return provider.complete(
                [{"role": "user", "content": prompt}],
                model=route.model,
                temperature=0,
            )

        issues = self._critic.critique(spec_md, sheet, provider_complete_fn=_complete)
        issues_dicts = [i.to_dict() for i in issues]
        critic_pass_count = int(state.get("critic_pass_count", 0)) + 1
        unresolved = count_unresolved_blocking(issues)

        self.writer.write_json(
            "review/checklist_issues.json",
            {"pass": critic_pass_count, "unresolved_blocking": unresolved, "issues": issues_dicts},
            overwrite=True,
        )
        if "review/checklist_issues.json" not in created:
            created.append("review/checklist_issues.json")

        return {
            "status": STATUS_CRITIQUING,
            "structured_issues": issues_dicts,
            "critic_pass_count": critic_pass_count,
            "created_artifacts": created,
        }

    def compose_candidate(self, state: WorkflowState) -> dict[str, Any]:
        """Promote the compiled draft to PASS_PENDING_USER_APPROVAL.

        spec_compile already wrote the draft; this node just promotes it.
        Falls back to recompile via SpecCompiler if the draft is missing/invalid.
        """
        created = list(state.get("created_artifacts", []))
        path = "draft/approval_candidate_spec.en.md"

        try:
            spec = self.writer.read_text(path)
        except Exception:
            spec = ""

        if not spec or not self._compiler.english_only(spec):
            manifest: dict[str, Any] = {}
            try:
                manifest = self.writer.read_json("context/project_manifest.json")
            except Exception:
                pass
            sheet_dict = state.get("requirement_lock_sheet")
            sheet = (
                RequirementLockSheet.from_dict(sheet_dict)
                if sheet_dict
                else RequirementLockSheet.build_fallback()
            )
            spec = self._compiler.compile(sheet, manifest)
            self.writer.write_text(path, spec, overwrite=True)

        if path not in created:
            created.append(path)
        return {
            "status": STATUS_PASS_PENDING_USER_APPROVAL,
            "approval_candidate_spec": str(self.writer.path(path)),
            "created_artifacts": created,
        }

    def critical_report(self, state: WorkflowState) -> dict[str, Any]:
        """Generate a failed draft and critical report when the pipeline is blocked."""
        manifest: dict[str, Any] = {}
        try:
            manifest = self.writer.read_json("context/project_manifest.json")
        except Exception:
            pass

        sheet_dict = state.get("requirement_lock_sheet")
        sheet = (
            RequirementLockSheet.from_dict(sheet_dict)
            if sheet_dict
            else RequirementLockSheet.build_fallback()
        )
        failed_draft = self._compiler.compile(sheet, manifest)
        report = self._critical_reporter.generate(state)

        created = list(state.get("created_artifacts", []))
        self.writer.write_text("critical/FAILED_AGENT_SPEC_DRAFT.en.md", failed_draft)
        self.writer.write_text("critical/CRITICAL_REPORT.ko.md", report)
        created.extend(["critical/FAILED_AGENT_SPEC_DRAFT.en.md", "critical/CRITICAL_REPORT.ko.md"])
        return {
            "status": STATUS_CRITICAL_BLOCKED,
            "critical_report": str(self.writer.path("critical/CRITICAL_REPORT.ko.md")),
            "created_artifacts": created,
        }

    def _maybe_execute_guarded_command(self, state: WorkflowState) -> None:
        """Run a guarded diagnostic command if command execution is allowed."""
        if not state.get("command_execution_allowed", False):
            return
        command_log_path = state.get("command_log_path")
        if not command_log_path:
            return
        working_directory = state.get("project_dir") or state.get("output_dir")
        if not working_directory:
            return
        command = ["pytest", "--version"]
        try:
            result = execute_command_guarded(
                command,
                working_directory=working_directory,
                requesting_agent="compiler",
                allowed=True,
                timeout_seconds=30,
            )
        except Exception as exc:
            result = {
                "command": command,
                "working_directory": str(working_directory),
                "exit_code": -1,
                "stdout_summary": "",
                "stderr_summary": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "requesting_agent": "compiler",
            }
        append_guarded_command_result(
            result,
            command_log_path=command_log_path,
            evidence_registry=self.evidence,
        )
