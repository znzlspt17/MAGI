"""CI는 CLI 없이 릴리스 API를 호출하며 보안 검사 실패 시 게시하지 않는다."""

import ast
import json
from pathlib import Path
import textwrap
from unittest.mock import Mock

import pytest

from deploy import artifacts


def test_release_inputs_are_available():
    assert set(artifacts.release_inputs()) == {"compose.portainer.yaml", "Caddyfile"}


def test_failed_security_scan_prevents_publish(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "summarize_scans", lambda output: False)
    run = Mock(side_effect=AssertionError("검사 실패 시 Docker를 호출하면 안 된다."))
    monkeypatch.setattr(artifacts, "run", run)
    with pytest.raises(ValueError, match="보안 검사를 통과하지 못한"):
        artifacts.publish(tmp_path / "release", "owner/repo", tmp_path / "images.txt")
    run.assert_not_called()


def test_scan_summary_still_rejects_fixable_critical(tmp_path):
    for role in artifacts.ROLES:
        (tmp_path / f"{role}.vulnerabilities.json").write_text(json.dumps({"SchemaVersion": 2, "Results": []}), encoding="utf-8")
    assert artifacts.summarize_scans(tmp_path)
    (tmp_path / "backend.vulnerabilities.json").write_text(json.dumps({
        "SchemaVersion": 2, "Results": [{"Vulnerabilities": [{"Severity": "CRITICAL", "FixedVersion": "2.0"}]}],
    }), encoding="utf-8")
    assert not artifacts.summarize_scans(tmp_path)


def test_workflows_call_release_api_without_cli():
    root = Path(__file__).resolve().parents[2]
    imported = set()
    blocks = 0
    for name in ("verify.yml", "build-arm64.yml"):
        content = (root / ".github/workflows" / name).read_text(encoding="utf-8")
        assert "deploy/release.py" not in content
        body = None
        for line in content.splitlines():
            if line.strip().endswith("python - <<'PY'"):
                body = []
            elif body is not None and line.strip() == "PY":
                tree = ast.parse(textwrap.dedent("\n".join(body)))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module == "deploy.artifacts":
                        imported.update(alias.name for alias in node.names)
                blocks += 1
                body = None
            elif body is not None:
                body.append(line)
        assert body is None
    assert blocks == 4
    assert imported == {"release_inputs", "smoke", "summarize_scans", "publish"}
