"""서비스 경계와 LangGraph 상태 계약의 퇴행을 방지한다."""
import ast
from pathlib import Path
from typing import get_type_hints

import pytest

from backend.models import State, WorkflowState


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("directory,forbidden", [
    ("protocol", ("backend", "gateway")),
    ("gateway", ("backend",)),
    ("backend/application", ("backend.server", "gateway")),
    ("backend/services/stop_diagnostics.py", ("backend.infrastructure", "backend.server", "backend.pipeline", "gateway")),
    ("backend/services/execution_segment.py", ("backend.infrastructure", "backend.server", "backend.pipeline", "gateway")),
])
def test_dependency_direction(directory, forbidden):
    target = ROOT / directory
    paths = [target] if target.is_file() else target.rglob("*.py")
    violations = []
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            imports = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                       else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for name in imports:
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {name}")
    assert not violations, "\n".join(violations)


def test_graph_state_preserves_persisted_state_field_types():
    state = get_type_hints(State)
    graph = get_type_hints(WorkflowState)
    assert {key: graph.get(key) for key in state} == state
    assert set(graph) - set(state) == {"_interview_direction_changing"}
