"""저장 이력 해석과 공개 상세 응답 조립. DB 접근은 호출자가 담당한다."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from backend.services.stop_diagnostics import saved_diagnostic, stop_diagnostic


@dataclass(frozen=True)
class HistoryNode:
    raw: dict[str, Any]
    result: dict[str, Any]
    captured: dict[str, Any]
    incomplete: bool

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> HistoryNode:
        incomplete = False
        records: dict[str, dict[str, Any]] = {}
        for key in ("result", "detail"):
            value = raw.get(key)
            if value is None:
                records[key] = {}
            elif isinstance(value, dict):
                records[key] = value
            else:
                records[key] = {}
                incomplete = True
        captured = records["detail"]
        nested = captured.get("result")
        result = {key: captured[key] for key in ("issues", "resolved_issues", "requirements") if key in captured}
        if nested is not None:
            if isinstance(nested, dict):
                # 2026-11-05: 현재 단계 결과가 과거에 캡처한 상세보다 우선한다.
                result.update(nested)
            else:
                incomplete = True
        result.update(records["result"])
        return cls(raw, result, captured, incomplete)

    @property
    def execution_id(self) -> str | None:
        value = self.raw.get("execution_id")
        return value if isinstance(value, str) and value else None

    @property
    def blocked(self) -> bool:
        return self.result.get("status") == "CRITICAL_BLOCKED" or (
            self.raw.get("stage") in {"workflow", "critical_report"} and self.raw.get("status") == "blocked")

    def evidence(self) -> dict[str, Any]:
        evidence = {key: self.result[key] for key in
                    ("structured_issues", "resolution_history", "stop_reason", "task_results") if key in self.result}
        # 캡처한 최신 목록은 과거 결과의 다른 필드 이름보다 우선한다.
        if "issues" in self.result:
            evidence["structured_issues"] = self.result["issues"]
        return evidence


def restore_diagnostic(node: HistoryNode, earlier: list[dict[str, Any]], position: int) -> dict[str, Any]:
    stored = saved_diagnostic(node.result.get("stop_diagnostic"))
    if stored is not None:
        return stored.model_dump()
    evidence: dict[str, Any] = {}
    if node.execution_id is not None:
        for index in range(position):
            raw = earlier[index]
            if raw.get("execution_id") == node.execution_id:
                evidence.update(HistoryNode.parse(raw).evidence())
    evidence.update(node.evidence())
    return stop_diagnostic(evidence)


def detail_payload(nodes: list[dict[str, Any]], step_id: str, *,
                   summarize: Callable[[dict[str, Any]], dict[str, Any]],
                   read_document: Callable[[dict[str, Any]], str | None]) -> dict[str, Any] | None:
    selected = next(((index, raw) for index, raw in enumerate(nodes) if raw.get("id") == step_id), None)
    if selected is None:
        return None
    position, raw = selected
    node = HistoryNode.parse(raw)
    result = dict(node.result)
    if node.blocked:
        result["stop_diagnostic"] = restore_diagnostic(node, nodes, position)
    payload = {**summarize(raw), "result": result}
    incomplete = node.incomplete
    for source, key, expected in (
        (node.captured, "change_review", dict), (node.captured, "review_snapshot_id", str),
        (node.captured, "approval_review", dict),
        (result, "research", dict), (raw, "usage", dict),
    ):
        if key not in source:
            continue
        if isinstance(source[key], expected):
            payload[key] = source[key]
        else:
            incomplete = True
    if "model_calls" in raw:
        if isinstance(raw["model_calls"], list):
            from backend.infrastructure.call_usage import public_model_calls
            payload["model_calls"] = public_model_calls(raw["model_calls"])
        else:
            incomplete = True
    document = node.captured.get("document")
    if document is not None:
        if isinstance(document, dict):
            content = read_document(document)
            if content is not None:
                payload["document"] = {**document, "content": content}
            else:
                incomplete = True
        else:
            incomplete = True
    if incomplete:
        payload["recording_incomplete"] = True
    return deepcopy(payload)
