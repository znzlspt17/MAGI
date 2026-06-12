"""Public engine API for MAGI Spec Engine."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from magi_spec.core.artifacts import ArtifactWriter
from magi_spec.core.config import MagiConfig, VALID_WEB_SEARCH_MODES
from magi_spec.core.errors import InvalidStateError, MagiError, MissingCredentialError
from magi_spec.core.evidence import EvidenceRegistry
from magi_spec.core.heartbeat import HEARTBEAT_PATH, RunHeartbeat
from magi_spec.core.state import (
    STATUS_FINALIZED,
    STATUS_NEEDS_USER_INPUT,
    STATUS_PASS_PENDING_USER_APPROVAL,
    STATUS_REJECTED_BY_USER,
    MagiState,
)
from magi_spec.graph.nodes import WorkflowNodes
from magi_spec.pipeline.builder import build_v2_workflow
from magi_spec.providers import default_provider_factory
from magi_spec.providers.base import ProviderFactory
from magi_spec.skills.registry import build_default_skill_registry


SUPPORTED_INPUT_EXTENSIONS = {".md", ".txt"}


@dataclass(slots=True)
class MagiResult:
    status: str
    output_dir: str
    approval_candidate_path: str | None = None
    final_spec_path: str | None = None
    critical_report_path: str | None = None
    state_path: str | None = None
    heartbeat_path: str | None = None
    questions_path: str | None = None


class MagiSpecEngine:
    def __init__(
        self,
        *,
        config: MagiConfig | None = None,
        providers: ProviderFactory | None = None,
    ) -> None:
        self.config = config or MagiConfig.default()
        self.providers = providers or default_provider_factory()

    @classmethod
    def with_mock_providers(cls) -> "MagiSpecEngine":
        return cls(config=MagiConfig.mock())

    def generate_from_file(
        self,
        *,
        input_path: str,
        output_dir: str,
        project_dir: str | None = None,
        web_search_mode: str | None = None,
        allow_command_execution: bool = False,
        overwrite: bool = False,
    ) -> MagiResult:
        path = Path(input_path)
        if not path.exists():
            raise FileNotFoundError(f"Input file does not exist: {input_path}")
        if path.suffix.lower() not in SUPPORTED_INPUT_EXTENSIONS:
            raise MagiError(
                f"Unsupported input extension '{path.suffix}'. Supported: .md, .txt"
            )
        return self.generate_from_text(
            text=path.read_text(encoding="utf-8"),
            output_dir=output_dir,
            project_dir=project_dir,
            web_search_mode=web_search_mode,
            allow_command_execution=allow_command_execution,
            input_source=str(path.resolve()),
            overwrite=overwrite,
        )

    def generate_from_text(
        self,
        *,
        text: str,
        output_dir: str,
        project_dir: str | None = None,
        web_search_mode: str | None = None,
        allow_command_execution: bool = False,
        input_source: str = "direct_text",
        overwrite: bool = False,
    ) -> MagiResult:
        self.config.validate()
        self._validate_web_search_mode(web_search_mode)
        self._validate_provider_credentials()
        writer = ArtifactWriter(output_dir, allow_overwrite=overwrite)
        writer.prepare()
        evidence = EvidenceRegistry()
        evidence.add("USER_REQUEST", "Original user request was captured.", input_source)
        created: list[str] = []

        writer.write_text("raw/user_request.md", text)
        writer.write_json("execution/command_log.json", {"commands": []})
        writer.write_json(
            "state/private_model_assignments.json",
            self.config.private_model_assignments(),
        )
        created.extend(
            [
                "raw/user_request.md",
                "execution/command_log.json",
                "state/private_model_assignments.json",
            ]
        )

        state = MagiState(
            run_id=f"magi_{uuid4().hex[:12]}",
            status="DRAFT",
            user_request=text,
            input_source=input_source,
            project_dir=str(Path(project_dir).resolve()) if project_dir else None,
            output_dir=str(Path(output_dir).resolve()),
            web_search_mode=web_search_mode or self.config.web_search,
            command_execution_allowed=allow_command_execution or self.config.command_execution,
            pipeline_version=self.config.pipeline_version,
            evidence_registry_path=str(writer.path("evidence/evidence_registry.json")),
            command_log_path=str(writer.path("execution/command_log.json")),
            created_artifacts=created,
            max_critic_passes=self.config.max_critic_passes,
        )
        return self._run_workflow(state, writer, evidence)

    def approve(self, output_dir: str) -> MagiResult:
        writer = ArtifactWriter(output_dir, allow_overwrite=False)
        state = self._load_state(writer)
        if state.status != STATUS_PASS_PENDING_USER_APPROVAL:
            raise InvalidStateError(
                "Approval attempted before the run is ready. "
                f"Expected {STATUS_PASS_PENDING_USER_APPROVAL}, got {state.status}."
            )
        candidate = Path(state.approval_candidate_spec or "")
        if not candidate.exists():
            raise InvalidStateError("Approval candidate does not exist.")
        final_path = writer.path("final/FINAL_AGENT_SPEC.md")
        if final_path.exists():
            raise InvalidStateError(f"Final spec already exists: {final_path}")
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(candidate, final_path)
        state.status = STATUS_FINALIZED
        state.user_approval_status = "APPROVED"
        state.final_agent_spec = str(final_path)
        state.created_artifacts.append("final/FINAL_AGENT_SPEC.md")
        self._persist_state(writer, state)
        return self._result_from_state(state)

    def revise(self, *, output_dir: str, feedback_path: str) -> MagiResult:
        writer = ArtifactWriter(output_dir, allow_overwrite=True)
        state = self._load_state(writer)
        feedback = Path(feedback_path).read_text(encoding="utf-8")
        state.status = STATUS_REJECTED_BY_USER
        state.user_approval_status = "REJECTED"
        state.user_request = (
            state.user_request.rstrip()
            + "\n\nRevision feedback to incorporate before approval:\n"
            + feedback.strip()
            + "\n"
        )
        writer.write_text("raw/revision_feedback.md", feedback, overwrite=True)
        evidence = EvidenceRegistry.from_dict(writer.read_json("evidence/evidence_registry.json"))
        evidence.add("USER_REQUEST", "User revision feedback was captured.", feedback_path)

        # Reset critic/compile state; re-enter at spec_compile
        state.structured_issues = []
        state.critic_pass_count = 0
        state.approval_candidate_spec = None
        state.final_agent_spec = None

        return self._run_workflow(state, writer, evidence)

    def answer(self, output_dir: str, *, answers: list[dict]) -> MagiResult:
        """Inject user answers to blocking questions and resume the pipeline."""
        writer = ArtifactWriter(output_dir, allow_overwrite=True)
        state = self._load_state(writer)

        from magi_spec.schemas.requirement_lock import QAItem, RequirementLockSheet

        sheet = (
            RequirementLockSheet.from_dict(state.requirement_lock_sheet)
            if state.requirement_lock_sheet
            else RequirementLockSheet.build_fallback()
        )

        answered_ids = {a["question_id"] for a in answers if isinstance(a, dict)}
        sheet.user_answers.extend(
            QAItem(
                question_id=str(a.get("question_id", "")),
                question=str(a.get("question", "")),
                answer=str(a.get("answer", "")),
            )
            for a in answers
            if isinstance(a, dict)
        )
        sheet.unresolved_questions = [
            q for q in sheet.unresolved_questions if q not in answered_ids
        ]
        state.requirement_lock_sheet = sheet.to_dict()
        state.blocking_questions = list(sheet.unresolved_questions)

        # Reset compile/critic state
        state.structured_issues = []
        state.critic_pass_count = 0
        state.approval_candidate_spec = None
        state.final_agent_spec = None

        evidence = EvidenceRegistry.from_dict(writer.read_json("evidence/evidence_registry.json"))
        evidence.add("USER_REQUEST", "User answers to blocking questions were incorporated.", output_dir)
        return self._run_workflow(state, writer, evidence)

    def status(self, output_dir: str) -> MagiResult:
        writer = ArtifactWriter(output_dir, allow_overwrite=False)
        state = self._load_state(writer)
        return self._result_from_state(state)

    def _run_workflow(
        self,
        state: MagiState,
        writer: ArtifactWriter,
        evidence: EvidenceRegistry,
    ) -> MagiResult:
        skills = build_default_skill_registry()
        nodes = WorkflowNodes(
            writer=writer,
            config=self.config,
            providers=self.providers,
            skills=skills,
            evidence=evidence,
        )
        workflow = build_v2_workflow(nodes)

        if HEARTBEAT_PATH not in state.created_artifacts:
            state.created_artifacts.append(HEARTBEAT_PATH)
        heartbeat = RunHeartbeat(writer=writer, state=state)
        heartbeat.start()
        try:
            final_state = MagiState.from_workflow_state(workflow.invoke(state.to_workflow_state()))
            heartbeat.stop(final_status=final_state.status)
        except Exception as exc:
            heartbeat.stop(exc=exc)
            raise
        writer.write_json("evidence/evidence_registry.json", evidence.to_dict(), overwrite=True)
        if "evidence/evidence_registry.json" not in final_state.created_artifacts:
            final_state.created_artifacts.append("evidence/evidence_registry.json")
        final_state.evidence_registry_path = str(writer.path("evidence/evidence_registry.json"))
        self._persist_state(writer, final_state)
        return self._result_from_state(final_state)

    def _persist_state(self, writer: ArtifactWriter, state: MagiState) -> None:
        if "state/magi_state.json" not in state.created_artifacts:
            state.created_artifacts.append("state/magi_state.json")
        writer.write_json("state/magi_state.json", state.to_dict(), overwrite=True)

    def _load_state(self, writer: ArtifactWriter) -> MagiState:
        path = writer.path("state/magi_state.json")
        if not path.exists():
            raise InvalidStateError(f"MAGI state file does not exist: {path}")
        try:
            return MagiState.from_dict(writer.read_json("state/magi_state.json"))
        except Exception as exc:
            raise InvalidStateError(f"Malformed MAGI state file: {path}") from exc

    def _result_from_state(self, state: MagiState) -> MagiResult:
        questions_path = None
        if state.status == STATUS_NEEDS_USER_INPUT:
            p = Path(state.output_dir) / "analysis" / "05_blocking_questions.ko.md"
            if p.exists():
                questions_path = str(p)
        return MagiResult(
            status=state.status,
            output_dir=state.output_dir,
            approval_candidate_path=state.approval_candidate_spec,
            final_spec_path=state.final_agent_spec,
            critical_report_path=state.critical_report,
            state_path=str(Path(state.output_dir) / "state" / "magi_state.json"),
            heartbeat_path=str(Path(state.output_dir) / HEARTBEAT_PATH),
            questions_path=questions_path,
        )

    def _validate_provider_credentials(self) -> None:
        for route in self.config.model_routing.values():
            provider = route.provider
            if provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
                raise MissingCredentialError(
                    "OpenAI provider selected but OPENAI_API_KEY is not set. "
                    "Set OPENAI_API_KEY or use the mock provider in tests."
                )
            if provider == "mock":
                continue
            if provider != "openai":
                raise MagiError(
                    f"Provider '{provider}' is a future extension stub and is not supported "
                    "for production runtime. Use provider 'openai' or 'mock' for tests."
                )

    def _validate_web_search_mode(self, mode: str | None) -> None:
        if mode is None:
            return
        if mode not in VALID_WEB_SEARCH_MODES:
            raise MagiError(
                f"Invalid web_search_mode '{mode}'. Allowed values are: auto, on, off."
            )
