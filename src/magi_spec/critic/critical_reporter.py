"""Critical report generation — pipeline-agnostic failure reporter."""

from __future__ import annotations

from magi_spec.core.config import MagiConfig
from magi_spec.core.evidence import EvidenceRegistry
from magi_spec.core.prompts import load_prompt
from magi_spec.core.provider_output import extract_json_object
from magi_spec.core.state import WorkflowState
from magi_spec.providers.base import ProviderFactory
from magi_spec.schemas.issue_packet import parse_issue_list
from magi_spec.schemas.provider_packets import choose_critical_report_markdown
from magi_spec.skills.registry import SkillRegistry


class CriticalReporter:
    """Generates a Korean Markdown critical report when the pipeline cannot proceed.

    Works for both v1 (3-agent loop) and v2 (SpecForge checklist critic) pipelines.
    Routes through 'critical_reporter' key in model_routing.
    """

    agent_id = "critical_reporter"

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

    def generate(self, state: WorkflowState) -> str:
        self.skills.assert_allowed(self.agent_id, "generate_critical_report")
        fallback = self._fallback_report(state)
        route = self.config.model_routing[self.agent_id]
        provider = self.providers.get(route.provider)
        raw_output = provider.complete(
            [{"role": "user", "content": self._report_prompt(state)}],
            model=route.model,
            temperature=0,
        )
        parsed = extract_json_object(raw_output)
        return choose_critical_report_markdown(
            parsed,
            raw_output=raw_output,
            fallback=fallback,
        )

    # ── prompt ───────────────────────────────────────────────────────────────

    def _report_prompt(self, state: WorkflowState) -> str:
        pipeline = state.get("pipeline_version", "v1")
        context = self._build_context(state, pipeline)
        return "\n\n".join([
            load_prompt("critical_reporter"),
            context,
            "Return only JSON with key critical_report_markdown.",
            "The value must be Korean Markdown and must not expose hidden reasoning.",
        ])

    def _build_context(self, state: WorkflowState, pipeline: str) -> str:
        import json
        if pipeline == "v2":
            issues_raw = state.get("structured_issues", [])
            issues = parse_issue_list({"issues": issues_raw})
            blocking = [i for i in issues if i.blocking and i.status != "resolved"]
            return json.dumps({
                "pipeline": "v2",
                "critic_pass_count": state.get("critic_pass_count", 0),
                "max_critic_passes": state.get("max_critic_passes", 2),
                "blocking_questions": state.get("blocking_questions", []),
                "request_type": state.get("request_type", ""),
                "unresolved_blocking_issues": [
                    {"checklist_id": i.checklist_id, "problem": i.problem, "required_change": i.required_change}
                    for i in blocking
                ],
                "total_issues": len(issues),
            }, ensure_ascii=False, indent=2)
        else:
            # v1: pass relevant v1-specific context
            failed_sections = [
                {"section": s, "status": st}
                for s, st in state.get("section_status", {}).items()
                if st != "PASS"
            ]
            return json.dumps({
                "pipeline": "v1",
                "current_round": state.get("current_round", 0),
                "blocking_questions": state.get("blocking_questions", []),
                "failed_sections": failed_sections,
                "conflict_report_count": len(state.get("conflict_reports", [])),
            }, ensure_ascii=False, indent=2)

    # ── fallback report ───────────────────────────────────────────────────────

    def _fallback_report(self, state: WorkflowState) -> str:
        pipeline = state.get("pipeline_version", "v1")
        if pipeline == "v2":
            return self._fallback_report_v2(state)
        return self._fallback_report_v1(state)

    def _fallback_report_v2(self, state: WorkflowState) -> str:
        issues_raw = state.get("structured_issues", [])
        issues = parse_issue_list({"issues": issues_raw})
        blocking = [i for i in issues if i.blocking and i.status != "resolved"]
        blocking_lines = [
            f"- [{i.checklist_id}] {i.problem} → 필요 수정: {i.required_change}"
            for i in blocking
        ] or ["- 차단 이슈 없음 (critic 응답 파싱 실패로 추정)"]

        question_lines = [
            f"- {q}" for q in state.get("blocking_questions", [])
        ] or ["- 없음"]

        passes = state.get("critic_pass_count", 0)
        max_passes = state.get("max_critic_passes", 2)

        return "\n".join([
            "# CRITICAL REPORT",
            "",
            "## 미해결 충돌",
            f"- SpecForge Checklist Critic가 최대 {max_passes}회 실행 후에도 blocking 이슈를 해소하지 못했습니다.",
            f"- 실행 횟수: {passes}회",
            "",
            "## 미해결 Blocking 이슈",
            *blocking_lines,
            "",
            "## 차단 질문",
            *question_lines,
            "",
            "## 사용자 권장 결정",
            "- `magi-spec answer`로 차단 질문에 답변을 제공하세요.",
            "- blocking 이슈의 required_change 항목을 확인해 요청 내용을 구체화하세요.",
            "- `magi-spec revise --feedback feedback.md`로 명세 방향을 수정하세요.",
            "",
            "## 실패한 영어 초안",
            "- `critical/FAILED_AGENT_SPEC_DRAFT.en.md`",
            "",
            "## 증거 요약",
            f"- 기록된 증거 수: {len(self.evidence.items)}",
            "",
            "이 보고서는 사용자에게 의사결정이 필요한 지점을 요약하며, 숨겨진 추론 원문은 포함하지 않습니다.",
        ])

    def _fallback_report_v1(self, state: WorkflowState) -> str:
        failed_sections = [
            f"- `{section}`: {status}"
            for section, status in state.get("section_status", {}).items()
            if status != "PASS"
        ] or ["- 명시적인 실패 섹션은 없지만 최대 라운드 내 합의에 도달하지 못했습니다."]

        revision_summary = [
            f"- 수행 라운드 수: {state.get('current_round', 0)}",
            f"- 누적 충돌 조정 보고서 수: {len(state.get('conflict_reports', []))}",
            "- 마지막 라운드 기준으로 unresolved 섹션을 유지한 채 최대 라운드에 도달했습니다.",
        ]

        failing_agent_lines = _v1_failing_agent_lines(state)

        return "\n".join([
            "# CRITICAL REPORT",
            "",
            "## 미해결 충돌",
            "- MAGI v1 리뷰 루프가 최대 라운드 내 만장일치 PASS에 도달하지 못했습니다.",
            "",
            "## 실패 섹션",
            *failed_sections,
            "",
            "## 섹션별 실패 에이전트",
            *failing_agent_lines,
            "",
            "## 반복 실패 패턴",
            "- 요구사항, 아키텍처 또는 실패 모드 검토 중 하나 이상이 반복적으로 PASS 조건을 만족하지 못했습니다.",
            "",
            "## 안전하지 않은 가정",
            "- 사용자 확인 없이 구현 방향을 바꿀 수 있는 가정은 최종 명세로 승격하지 않았습니다.",
            "",
            "## 차단 질문",
            *(f"- {question}" for question in state.get("blocking_questions", [])),
            "",
            "## 시도한 수정 요약",
            *revision_summary,
            "",
            "## 사용자 권장 결정",
            "- 실패 섹션의 우선순위를 지정해 어떤 요구사항을 먼저 확정할지 결정합니다.",
            "- 차단 질문에 대한 답을 제공해 리뷰 기준을 고정합니다.",
            "- 필요 시 범위를 축소해 최대 라운드 내 합의 가능성을 높입니다.",
            "",
            "## 실패한 영어 초안",
            "- `critical/FAILED_AGENT_SPEC_DRAFT.en.md`",
            "",
            "## 증거 요약",
            f"- 기록된 증거 수: {len(self.evidence.items)}",
            "",
            "이 보고서는 사용자에게 의사결정이 필요한 지점을 요약하며, 숨겨진 추론 원문은 포함하지 않습니다.",
        ])


def _v1_failing_agent_lines(state: WorkflowState) -> list[str]:
    """Extract failing agent info from v1 agent outputs."""
    agent_map = {
        "melchior": state.get("melchior_outputs", []),
        "balthasar": state.get("balthasar_outputs", []),
        "casper": state.get("casper_outputs", []),
    }
    latest = {
        name: dict(outputs[-1]) if outputs else {}
        for name, outputs in agent_map.items()
    }
    lines: list[str] = []
    for section, status in state.get("section_status", {}).items():
        if status == "PASS":
            continue
        failing = [
            f"{name.upper()}({out.get('section_status', {}).get(section, 'PASS')})"
            for name, out in latest.items()
            if out.get("section_status", {}).get(section, "PASS") != "PASS"
        ]
        lines.append(
            f"- `{section}`: {', '.join(failing)}" if failing
            else f"- `{section}`: 실패 에이전트 식별 정보 없음"
        )
    return lines or ["- 섹션 단위 실패 에이전트 없음"]
