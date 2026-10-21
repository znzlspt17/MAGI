"""파이프라인 단계가 공유하는 의존성."""

from __future__ import annotations
from dataclasses import dataclass

from backend.config import Config
from backend.infrastructure.artifact_writer import ArtifactWriter
from backend.infrastructure.evidence_registry import EvidenceRegistry
from backend.providers.llm_provider import OpenAIProvider
from backend.services.checklist_critic import ChecklistCritic
from backend.services.critical_reporter import CriticalReporter
from backend.services.interviewer import SpecInterviewer
from backend.services.requirement_lock_builder import RequirementLockBuilder
from backend.services.skill_registry import SkillRegistry
from backend.services.spec_compiler import SpecCompiler


@dataclass(slots=True)
class PipelineContext:
    writer: ArtifactWriter
    config: Config
    provider: OpenAIProvider
    skills: SkillRegistry
    evidence: EvidenceRegistry
    interviewer: SpecInterviewer
    lock_builder: RequirementLockBuilder
    compiler: SpecCompiler
    critic: ChecklistCritic
    critical_reporter: CriticalReporter
