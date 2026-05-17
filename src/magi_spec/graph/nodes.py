"""LangGraph node implementations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from magi_spec.agents import (
    BalthasarAgent,
    CasperAgent,
    ConflictResolver,
    CriticalReporter,
    MelchiorAgent,
    SpecComposer,
)
from magi_spec.agents.base import DEFAULT_SECTION_STATUS
from magi_spec.core.artifacts import ArtifactWriter
from magi_spec.core.config import MagiConfig
from magi_spec.core.evidence import EvidenceRegistry
from magi_spec.core.state import (
    STATUS_ANALYZING,
    STATUS_CRITICAL_BLOCKED,
    STATUS_PASS_PENDING_USER_APPROVAL,
    STATUS_RESEARCHING,
    STATUS_REVIEWING,
    WorkflowState,
)
from magi_spec.providers.base import ProviderFactory
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
        self.melchior = MelchiorAgent(
            config=config, providers=providers, skills=skills, evidence=evidence
        )
        self.balthasar = BalthasarAgent(
            config=config, providers=providers, skills=skills, evidence=evidence
        )
        self.casper = CasperAgent(config=config, providers=providers, skills=skills, evidence=evidence)
        self.conflict_resolver = ConflictResolver(skills=skills, evidence=evidence)
        self.spec_composer = SpecComposer(skills=skills, evidence=evidence)
        self.critical_reporter = CriticalReporter(skills=skills, evidence=evidence)

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
        self.writer.write_text("research/web_research_summary.ko.md", summarize_web_research(sources, mode))
        created.extend(["research/web_sources.json", "research/web_research_summary.ko.md"])
        return {
            "status": STATUS_RESEARCHING,
            "web_sources_path": str(self.writer.path("research/web_sources.json")),
            "created_artifacts": created,
        }

    def analysis(self, state: WorkflowState) -> dict[str, Any]:
        request = state.get("user_request", "").strip()
        assumptions = [
            "사용자가 명시하지 않은 세부 구현 방식은 기존 프로젝트 관례를 우선한다.",
            "최종 산출물은 구현 에이전트가 바로 사용할 수 있는 영어 Markdown 명세다.",
        ]
        blocking_questions: list[str] = []
        if not request:
            blocking_questions.append("사용자 요청이 비어 있어 구현 방향을 결정할 수 없습니다.")
        intent = "\n".join(
            [
                "# 의도 분석",
                "",
                "사용자의 고수준 요청을 구현 가능한 명세로 변환하는 것이 목표입니다.",
                "원문 요청은 `raw/user_request.md`에 보존됩니다.",
            ]
        )
        requirement_lock = "\n".join(
            [
                "# 요구사항 잠금",
                "",
                "- MAGI는 대상 프로젝트를 직접 구현하지 않습니다.",
                "- 승인 후보가 PASS되어도 사용자 승인 전에는 최종 명세로 승격하지 않습니다.",
                "- 모델 제공자 정보는 agent-visible 문맥에 포함하지 않습니다.",
            ]
        )
        scope = "\n".join(
            [
                "# 범위 분류",
                "",
                "- Mandatory: 입력 요청 보존, 산출물 저장, 리뷰 루프, 승인 흐름.",
                "- Recommended: 프로젝트 컨텍스트와 웹 증거를 보조 정보로 활용.",
                "- Optional: 실제 외부 LLM 호출은 설정된 경우에만 수행.",
                "- Out of Scope: 구현 에이전트 실행, 배포, GUI, 웹 서비스.",
            ]
        )
        assumption_doc = "# 초기 가정\n\n" + "\n".join(f"- {item}" for item in assumptions) + "\n"
        question_doc = "# 차단 질문\n\n"
        question_doc += "\n".join(f"- {item}" for item in blocking_questions) if blocking_questions else "- 없음\n"

        created = list(state.get("created_artifacts", []))
        analysis_files = {
            "analysis/01_intent_parse.ko.md": intent,
            "analysis/02_requirement_lock.ko.md": requirement_lock,
            "analysis/03_scope_classification.ko.md": scope,
            "analysis/04_initial_assumptions.ko.md": assumption_doc,
            "analysis/05_blocking_questions.ko.md": question_doc,
        }
        for relative_path, content in analysis_files.items():
            self.writer.write_text(relative_path, content)
            created.append(relative_path)
        for assumption in assumptions:
            self.evidence.add("AGENT_ASSUMPTION", assumption, "analysis")
        return {
            "status": STATUS_ANALYZING,
            "intent_parse": intent,
            "requirement_lock": requirement_lock,
            "scope_classification": scope,
            "assumptions": assumptions,
            "blocking_questions": blocking_questions,
            "created_artifacts": created,
        }

    def initial_agents(self, state: WorkflowState) -> dict[str, Any]:
        created = list(state.get("created_artifacts", []))
        melchior = self.melchior.review(state, round_number=0).to_dict()
        balthasar = self.balthasar.review(state, round_number=0).to_dict()
        casper = self.casper.review(state, round_number=0).to_dict()
        outputs = [
            ("agents/initial/melchior_architecture.ko.md", melchior["content"]),
            ("agents/initial/balthasar_requirements.ko.md", balthasar["content"]),
            ("agents/initial/casper_failure_review.ko.md", casper["content"]),
        ]
        for relative_path, content in outputs:
            self.writer.write_text(relative_path, content)
            created.append(relative_path)
        return {
            "status": STATUS_REVIEWING,
            "melchior_outputs": [melchior],
            "balthasar_outputs": [balthasar],
            "casper_outputs": [casper],
            "section_status": dict(DEFAULT_SECTION_STATUS),
            "created_artifacts": created,
        }

    def review_round(self, state: WorkflowState) -> dict[str, Any]:
        round_number = int(state.get("current_round", 0)) + 1
        round_dir = f"review_rounds/round_{round_number:02d}"
        created = list(state.get("created_artifacts", []))

        melchior = self.melchior.review(state, round_number=round_number).to_dict()
        balthasar = self.balthasar.review(state, round_number=round_number).to_dict()
        casper = self.casper.review(state, round_number=round_number).to_dict()

        state_for_conflict = dict(state)
        state_for_conflict["melchior_outputs"] = list(state.get("melchior_outputs", [])) + [melchior]
        state_for_conflict["balthasar_outputs"] = list(state.get("balthasar_outputs", [])) + [balthasar]
        state_for_conflict["casper_outputs"] = list(state.get("casper_outputs", [])) + [casper]
        state_for_conflict["section_status"] = dict(DEFAULT_SECTION_STATUS)
        conflict = self.conflict_resolver.resolve(state_for_conflict, round_number=round_number).to_dict()

        artifacts = {
            f"{round_dir}/melchior_review.ko.md": melchior["content"],
            f"{round_dir}/balthasar_review.ko.md": balthasar["content"],
            f"{round_dir}/casper_review.ko.md": casper["content"],
            f"{round_dir}/conflict_resolution.ko.md": conflict["content"],
            f"{round_dir}/section_status.json": DEFAULT_SECTION_STATUS,
        }
        for relative_path, content in artifacts.items():
            if relative_path.endswith(".json"):
                self.writer.write_json(relative_path, content)
            else:
                self.writer.write_text(relative_path, str(content))
            created.append(relative_path)

        return {
            "status": STATUS_REVIEWING,
            "current_round": round_number,
            "melchior_outputs": state_for_conflict["melchior_outputs"],
            "balthasar_outputs": state_for_conflict["balthasar_outputs"],
            "casper_outputs": state_for_conflict["casper_outputs"],
            "conflict_reports": list(state.get("conflict_reports", [])) + [conflict],
            "section_status": dict(DEFAULT_SECTION_STATUS),
            "created_artifacts": created,
        }

    def compose_candidate(self, state: WorkflowState) -> dict[str, Any]:
        manifest = self.writer.read_json("context/project_manifest.json")
        spec = self.spec_composer.compose(state, manifest)
        if not self.spec_composer.english_only(spec):
            raise ValueError("Approval candidate must be English-only.")
        created = list(state.get("created_artifacts", []))
        self.writer.write_text("draft/approval_candidate_spec.en.md", spec)
        created.append("draft/approval_candidate_spec.en.md")
        return {
            "status": STATUS_PASS_PENDING_USER_APPROVAL,
            "approval_candidate_spec": str(self.writer.path("draft/approval_candidate_spec.en.md")),
            "created_artifacts": created,
        }

    def critical_report(self, state: WorkflowState) -> dict[str, Any]:
        manifest = self.writer.read_json("context/project_manifest.json")
        failed_draft = self.spec_composer.compose(state, manifest)
        report = self.critical_reporter.generate(state)
        created = list(state.get("created_artifacts", []))
        self.writer.write_text("critical/FAILED_AGENT_SPEC_DRAFT.en.md", failed_draft)
        self.writer.write_text("critical/CRITICAL_REPORT.ko.md", report)
        created.extend(["critical/FAILED_AGENT_SPEC_DRAFT.en.md", "critical/CRITICAL_REPORT.ko.md"])
        return {
            "status": STATUS_CRITICAL_BLOCKED,
            "critical_report": str(self.writer.path("critical/CRITICAL_REPORT.ko.md")),
            "created_artifacts": created,
        }


def all_agents_pass(state: WorkflowState) -> bool:
    outputs = [
        state.get("melchior_outputs", []),
        state.get("balthasar_outputs", []),
        state.get("casper_outputs", []),
    ]
    if not all(outputs):
        return False
    latest_pass = all(output[-1].get("status") == "PASS" for output in outputs)
    sections_pass = all(status == "PASS" for status in state.get("section_status", {}).values())
    return latest_pass and sections_pass
