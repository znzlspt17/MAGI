"""제거한 CLI는 실행할 수 없고 서버·컨테이너 진입점만 남는다."""

import ast
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("module", [
    "backend.access", "backend.knowledge", "backend.knowledge.prepare_model",
    "backend.knowledge.evaluate_embedding", "deploy.release", "deploy.measure",
])
def test_removed_cli_cannot_run(module):
    result = subprocess.run(
        [sys.executable, "-m", module, "--help"], cwd=ROOT,
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )
    assert result.returncode != 0
    assert "No module named" in result.stderr
    assert not result.stdout


def test_custom_cli_parsers_and_non_service_entrypoints_are_absent():
    allowed = {
        "backend/server/app.py", "backend/server/__main__.py",
        "protocol/container.py", "protocol/deployment.py",
    }
    for directory in ("backend", "gateway", "protocol", "deploy"):
        for path in (ROOT / directory).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                    assert "argparse" not in names, path
                if isinstance(node, ast.If) and "__name__" in ast.unparse(node.test):
                    assert path.relative_to(ROOT).as_posix() in allowed, path
