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


def test_smoke_checks_and_records_built_caddy_image(tmp_path, monkeypatch):
    commands = []

    def run(*args, **kwargs):
        commands.append(args)
        if args[:3] == ("git", "rev-parse", "HEAD"):
            return "test-commit"
        if args[:4] == ('docker', 'buildx', 'imagetools', 'inspect'):
            return json.dumps({'manifests': [{'platform': {'os': 'linux', 'architecture': 'arm64'}}]})
        if args[:3] == ("docker", "image", "inspect"):
            if args[3] == "magi-caddy:test-release":
                assert any(command[:3] == ("docker", "buildx", "build") for command in commands)
            return json.dumps([{"Architecture": "arm64", "Os": "linux", "Id": "sha256:built"}])

    monkeypatch.setattr(artifacts, "run", run)
    output = tmp_path / "release"
    artifacts.smoke(output, "test-release")
    manifest = json.loads((output / "release.json").read_text(encoding="utf-8"))
    assert manifest["images"]["caddy"]["id"] == "sha256:built"
    assert manifest['external_images']['rabbitmq'] == {'reference': artifacts.RABBITMQ, 'id': 'sha256:built', 'platform': 'linux/arm64'}
    build = next(command for command in commands if command[:3] == ("docker", "buildx", "build"))
    assert "--load" in build
    assert build[build.index("--platform") + 1] == "linux/arm64"
    assert build[build.index("--tag") + 1] == "magi-caddy:test-release"


def test_failed_security_scan_prevents_publish(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "summarize_scans", lambda output: False)
    run = Mock(side_effect=AssertionError("검사 실패 시 Docker를 호출하면 안 된다."))
    monkeypatch.setattr(artifacts, "run", run)
    with pytest.raises(ValueError, match="보안 검사를 통과하지 못한"):
        artifacts.publish(tmp_path / "release", "owner/repo", tmp_path / "images.txt")
    run.assert_not_called()


@pytest.mark.parametrize('role', ['backend', 'rabbitmq'])
def test_scan_summary_still_rejects_fixable_critical(tmp_path, role):
    for scanned in artifacts.SCAN_ROLES:
        (tmp_path / f"{scanned}.vulnerabilities.json").write_text(json.dumps({"SchemaVersion": 2, "Results": []}), encoding="utf-8")
    assert artifacts.summarize_scans(tmp_path)
    (tmp_path / f"{role}.vulnerabilities.json").write_text(json.dumps({
        "SchemaVersion": 2, "Results": [{"Vulnerabilities": [{"Severity": "CRITICAL", "FixedVersion": "2.0"}]}],
    }), encoding="utf-8")
    assert not artifacts.summarize_scans(tmp_path)


def test_missing_rabbitmq_scan_prevents_publication(tmp_path):
    for role in artifacts.ROLES:
        (tmp_path / f'{role}.vulnerabilities.json').write_text(json.dumps({'SchemaVersion': 2, 'Results': []}), encoding='utf-8')
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
    assert blocks == 6
    assert imported == {"release_inputs", "smoke", "summarize_scans", "publish"}
