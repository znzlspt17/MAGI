from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]


def workflow(name):
    return yaml.safe_load((ROOT / '.github/workflows' / name).read_text(encoding='utf-8'))


def test_verify_keeps_one_fail_closed_required_check():
    jobs = workflow('verify.yml')['jobs']
    assert set(jobs['verify']['needs']) == {'static', 'frontend', 'integration'}
    assert 'always()' in jobs['verify']['if']
    gate = jobs['verify']['steps'][0]
    assert all(f"needs.{job}.result" in gate['env'][job.upper()] for job in ('static', 'frontend', 'integration'))
    assert all(f'"${job.upper()}" = success' in gate['run'] for job in ('static', 'frontend', 'integration'))
    command = next(step['run'] for step in jobs['integration']['steps'] if step.get('name') == 'Product boundary tests with real PostgreSQL and checkpointer')
    assert '-m pytest -q' in command and '--durations=' in command and '--junitxml=' in command
    assert '--ignore' not in command and '-n ' not in command


def test_release_waits_for_verification_and_prepared_images():
    jobs = workflow('build-arm64.yml')['jobs']
    assert set(jobs['publish']['needs']) == {'verify', 'prepare'}
    assert 'needs' not in jobs['prepare']
    assert jobs['publish']['permissions']['packages'] == 'write'
    assert all("github.ref == format('refs/heads/{0}', github.event.repository.default_branch)" in jobs[job]['if'] for job in ('verify', 'prepare'))
    assert all('packages' not in jobs[job].get('permissions', {}) for job in ('verify', 'prepare'))
    commands = '\n'.join(step.get('run', '') for step in jobs['publish']['steps'])
    assert 'docker load' in commands and 'verify_release' in commands and 'publish(' in commands


def test_benchmark_never_publishes():
    jobs = workflow('benchmark-ci.yml')['jobs']
    assert set(jobs) == {'baseline_verify', 'baseline_prepare', 'optimized_verify', 'optimized_prepare', 'optimized_load'}
    assert jobs['baseline_prepare']['needs'] == 'baseline_verify'
    assert 'needs' not in jobs['optimized_prepare']
    assert 'publish' not in (ROOT / '.github/workflows/benchmark-ci.yml').read_text(encoding='utf-8').lower()


def test_scan_failure_cannot_be_masked_by_diagnostics():
    steps = workflow('prepare-arm64.yml')['jobs']['build']['steps']
    scans = [step for step in steps if step.get('name', '').startswith('Scan ')]
    assert len(scans) == 4
    assert all(step['with']['exit-code'] == '1' for step in scans)
    assert all("!cancelled()" in step['if'] for step in scans)
    summary = next(step for step in steps if step.get('name', '').startswith('Show vulnerability IDs'))
    assert '!cancelled()' in summary['if']
    assert {step['id'] for step in scans} == {'scan_backend', 'scan_gateway', 'scan_caddy', 'scan_rabbitmq'}
    for role in ('BACKEND', 'GATEWAY', 'CADDY', 'RABBITMQ'):
        assert f'steps.scan_{role.lower()}.outcome' in summary['env'][role]
        assert f'"${role}" = success' in summary['run']
    for name in ('Save checked images for the next job', 'Transfer checked images and reports'):
        condition = next(step['if'] for step in steps if step.get('name') == name)
        assert condition == '${{ inputs.transfer_images }}'


def test_transfer_artifact_is_scoped_to_attempt_and_variant():
    prepared = workflow('prepare-arm64.yml')
    prepare = prepared['jobs']['build']['steps']
    upload = next(step for step in prepare if step.get('name') == 'Transfer checked images and reports')
    assert upload['id'] == 'transfer'
    assert upload['with']['name'] == '${{ inputs.artifact_name }}-${{ github.run_attempt }}'
    assert 'steps.transfer.outputs.artifact-id' in prepared['jobs']['build']['outputs']['artifact_id']
    assert 'jobs.build.outputs.artifact_id' in prepared[True]['workflow_call']['outputs']['artifact_id']['value']
    load = workflow('load-arm64.yml')['jobs']['validate']['steps']
    download = next(step for step in load if step.get('uses', '').startswith('actions/download-artifact@'))
    assert download['with']['artifact-ids'] == '${{ inputs.artifact_id }}'
    release = workflow('build-arm64.yml')['jobs']['publish']
    assert next(step for step in release['steps'] if step.get('uses', '').startswith('actions/download-artifact@'))['with']['artifact-ids'] == '${{ needs.prepare.outputs.artifact_id }}'
    assert workflow('benchmark-ci.yml')['jobs']['optimized_load']['with']['artifact_id'] == '${{ needs.optimized_prepare.outputs.artifact_id }}'
