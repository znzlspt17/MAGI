"""파이프라인 단계를 조립하는 얇은 구성 객체."""

from __future__ import annotations

from backend.config import MagiConfig
from backend.infrastructure.artifact_writer import ArtifactWriter
from backend.infrastructure.evidence_registry import EvidenceRegistry
from backend.pipeline.context import PipelineContext
from backend.pipeline.stages.await_user_stage import AwaitUserStage
from backend.pipeline.stages.candidate_stage import CandidateStage
from backend.pipeline.stages.compile_stage import CompileStage
from backend.pipeline.stages.critical_report_stage import CriticalReportStage
from backend.pipeline.stages.interview_stage import InterviewStage
from backend.pipeline.stages.project_context_stage import ProjectContextStage
from backend.pipeline.stages.requirement_lock_stage import RequirementLockStage
from backend.pipeline.stages.review_stage import ReviewStage
from backend.pipeline.stages.review_resolution_stage import ReviewResolutionStage
from backend.pipeline.stages.web_research_stage import WebResearchStage
from backend.providers.llm_provider import OpenAIProvider
from backend.services.checklist_critic import ChecklistCritic
from backend.services.critical_reporter import CriticalReporter
from backend.services.interviewer import SpecInterviewer
from backend.services.requirement_lock_builder import RequirementLockBuilder
from backend.services.skill_registry import SkillRegistry
from backend.services.spec_compiler import SpecCompiler


class WorkflowNodes:
    """LangGraph가 호출할 단계 인스턴스를 구성한다."""

    def __init__(
        self,
        *,
        writer: ArtifactWriter,
        config: MagiConfig,
        provider: OpenAIProvider,
        skills: SkillRegistry,
        evidence: EvidenceRegistry,
    ) -> None:
        context = PipelineContext(
            writer=writer,
            config=config,
            provider=provider,
            skills=skills,
            evidence=evidence,
            interviewer=SpecInterviewer(),
            lock_builder=RequirementLockBuilder(),
            compiler=SpecCompiler(
                config=config, provider=provider, skills=skills, evidence=evidence
            ),
            critic=ChecklistCritic(),
            critical_reporter=CriticalReporter(
                config=config, provider=provider, skills=skills, evidence=evidence
            ),
        )
        self.project_context = ProjectContextStage(context)
        self.web_research = WebResearchStage(context)
        self.interview = InterviewStage(context)
        self.await_user = AwaitUserStage()
        self.requirement_lock_stage = RequirementLockStage(context)
        self.spec_compile = CompileStage(context)
        self.checklist_critic_node = ReviewStage(context)
        self.review_resolution = ReviewResolutionStage(context)
        self.compose_candidate = CandidateStage(context)
        self.critical_report = CriticalReportStage(context)
