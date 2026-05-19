"""Critical blocked report generation."""

from __future__ import annotations

from magi_spec.core.agent_context import build_agent_visible_context
from magi_spec.core.config import MagiConfig
from magi_spec.core.evidence import EvidenceRegistry
from magi_spec.core.prompts import load_prompt
from magi_spec.core.provider_output import extract_json_object
from magi_spec.core.state import WorkflowState
from magi_spec.providers.base import ProviderFactory
from magi_spec.schemas.provider_packets import choose_critical_report_markdown
from magi_spec.skills.registry import SkillRegistry


class CriticalReporter:
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

    def _fallback_report(self, state: WorkflowState) -> str:
        latest_outputs = {
            "MELCHIOR": _latest_output(state.get("melchior_outputs", [])),
            "BALTHASAR": _latest_output(state.get("balthasar_outputs", [])),
            "CASPER": _latest_output(state.get("casper_outputs", [])),
        }
        failed_sections = [
            f"- `{section}`: {status}"
            for section, status in state.get("section_status", {}).items()
            if status != "PASS"
        ]
        if not failed_sections:
            failed_sections = ["- 명시적인 실패 섹션은 없지만 최대 라운드 내 합의에 도달하지 못했습니다."]
        failing_agent_lines = _failing_agent_lines(state, latest_outputs)
        revision_summary = [
            f"- 수행 라운드 수: {state.get('current_round', 0)}",
            f"- 누적 충돌 조정 보고서 수: {len(state.get('conflict_reports', []))}",
            "- 마지막 라운드 기준으로 unresolved 섹션을 유지한 채 최대 라운드에 도달했습니다.",
        ]
        return "\n".join(
            [
                "# CRITICAL REPORT",
                "",
                "## 미해결 충돌",
                "- MAGI 리뷰 루프가 최대 라운드 내 만장일치 PASS에 도달하지 못했습니다.",
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
            ]
        )

    def _report_prompt(self, state: WorkflowState) -> str:
        return "\n\n".join(
            [
                load_prompt("critical_reporter"),
                build_agent_visible_context(
                    state,
                    agent_id=self.agent_id,
                    round_number=int(state.get("current_round", 0)),
                ),
                "Return only JSON with key critical_report_markdown.",
                "The value must be Korean Markdown and must not expose hidden reasoning.",
            ]
        )


def _latest_output(items: list[dict]) -> dict:
    if not items:
        return {}
    return dict(items[-1])


def _failing_agent_lines(
    state: WorkflowState,
    latest_outputs: dict[str, dict],
) -> list[str]:
    lines: list[str] = []
    section_status = state.get("section_status", {})
    for section, status in section_status.items():
        if status == "PASS":
            continue
        failing_agents: list[str] = []
        for agent_name, output in latest_outputs.items():
            agent_section_status = output.get("section_status", {}).get(section, "PASS")
            if agent_section_status != "PASS":
                failing_agents.append(f"{agent_name}({agent_section_status})")
        if failing_agents:
            lines.append(f"- `{section}`: {', '.join(failing_agents)}")
        else:
            lines.append(f"- `{section}`: 실패 에이전트 식별 정보 없음")
    if not lines:
        return ["- 섹션 단위 실패 에이전트 없음"]
    return lines
