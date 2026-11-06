import json
from pathlib import Path
import re
import textwrap
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_workflow_generates_readable_release_id():
    workflow = (ROOT / '.github/workflows/build-arm64.yml').read_text(encoding='utf-8')
    assert 'from deploy.version import release_id' in workflow
    assert 'GITHUB_ENV' in workflow
    assert 'github.sha }}-${{ github.run_id' not in workflow


def test_product_versions_are_consistent():
    with (ROOT / 'pyproject.toml').open('rb') as source:
        backend = tomllib.load(source)['project']['version']
    frontend = json.loads((ROOT / 'frontend/package.json').read_text(encoding='utf-8'))['version']
    assert backend == frontend


def test_workflow_exports_release_id_for_later_steps(tmp_path, monkeypatch):
    workflow = (ROOT / '.github/workflows/build-arm64.yml').read_text(encoding='utf-8')
    step = workflow.split('- name: Set readable release ID', 1)[1].split('      - uses:', 1)[0]
    script = step.split("python - <<'PY'\n", 1)[1].split('\n          PY', 1)[0]
    github_env = tmp_path / 'github-env'
    monkeypatch.setenv('GITHUB_ENV', str(github_env))
    monkeypatch.setenv('GITHUB_RUN_NUMBER', '123')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '2')
    monkeypatch.chdir(ROOT)
    exec(compile(textwrap.dedent(script), '<workflow>', 'exec'), {})
    with (ROOT / 'pyproject.toml').open('rb') as source:
        version = tomllib.load(source)['project']['version']
    assert github_env.read_text(encoding='utf-8') == f'RELEASE_ID=v{version}-build.123.2\n'


def test_release_id_reads_product_version_and_identifies_each_build(tmp_path):
    from deploy.version import release_id

    project = tmp_path / 'pyproject.toml'
    project.write_text('[project]\nversion = "2.13.4"\n', encoding='utf-8')
    assert release_id(project, '123', '1') == 'v2.13.4-build.123.1'
    assert release_id(project, '123', '2') == 'v2.13.4-build.123.2'
    assert re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,127}', release_id(project, '124', '1'))


@pytest.mark.parametrize('version', ['1.2', '1.2.3.4', 'v1.2.3', '1.02.3', '1.2.3-rc.1', '1.2.3\n'])
def test_release_id_rejects_invalid_product_versions(tmp_path, version):
    from deploy.version import release_id

    project = tmp_path / 'pyproject.toml'
    project.write_text('[project]\nversion = ' + json.dumps(version) + '\n', encoding='utf-8')
    with pytest.raises(ValueError):
        release_id(project, '1', '1')


@pytest.mark.parametrize(('build', 'attempt'), [('0', '1'), ('1', '0'), ('-1', '1'), ('1', '01'), ('x', '1'), ('1', '1\n')])
def test_release_id_rejects_invalid_build_numbers(tmp_path, build, attempt):
    from deploy.version import release_id

    project = tmp_path / 'pyproject.toml'
    project.write_text('[project]\nversion = "0.3.1"\n', encoding='utf-8')
    with pytest.raises(ValueError):
        release_id(project, build, attempt)
