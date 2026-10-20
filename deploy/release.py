"""ARM64 릴리스를 검증하고, 검사한 동일 이미지를 GHCR에 게시한다."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


CADDY = 'caddy:2-alpine@sha256:d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f'
ROLES = ('gateway', 'backend', 'caddy')
BASE_FILES = {'magi-images.tar', 'release.json', 'images.txt', 'compose.portainer.yaml',
              'Caddyfile', 'release.py', 'measure.py'}
SUPPORT_FILES = ('compose.portainer.yaml', 'Caddyfile', 'release.py', 'measure.py')
REPORTS = {f'{role}.{suffix}' for role in ROLES
           for suffix in ('spdx.json', 'vulnerabilities.json')}


def run(*args, capture=False, **kwargs):
    result = subprocess.run(args, check=True, text=True, capture_output=capture, **kwargs)
    return result.stdout.strip() if capture else None


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def release_inputs():
    # Git에서 제외한 로컬 문서는 릴리스 입력으로 요구하거나 복사하지 않는다.
    sources = {name: Path('deploy') / name for name in SUPPORT_FILES}
    missing = [str(path) for path in sources.values() if not path.is_file() or path.is_symlink()]
    if missing:
        raise ValueError('릴리스 필수 파일이 누락되었거나 일반 파일이 아닙니다: ' + ', '.join(missing))
    return sources


def build(output, release, revision):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,127}', release):
        raise ValueError('릴리스 이름은 Docker 태그 형식이어야 합니다.')
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('모델 revision은 40자리 commit SHA여야 합니다.')
    if run('git', 'status', '--porcelain', capture=True):
        raise ValueError('소스 식별을 위해 커밋된 깨끗한 체크아웃에서 빌드하세요.')
    sources = release_inputs()
    if output.exists() and any(output.iterdir()):
        raise ValueError('기존 릴리스를 덮어쓰지 않도록 빈 출력 경로를 지정하세요.')
    output.mkdir(parents=True, exist_ok=True)
    commit = run('git', 'rev-parse', 'HEAD', capture=True)
    images = {role: f'magi-{role}:{release}' for role in ROLES}
    for role in ('gateway', 'backend'):
        run('docker', 'buildx', 'build', '--platform', 'linux/arm64', '--target', role,
            '--tag', images[role], '--label', f'org.opencontainers.image.revision={commit}',
            '--build-arg', f'MODEL_REVISION={revision}',
            '--load', '--provenance=false', '.')
    run('docker', 'pull', '--platform', 'linux/arm64', CADDY)
    run('docker', 'image', 'tag', CADDY, images['caddy'])
    metadata = {}
    for role, tag in images.items():
        info = json.loads(run('docker', 'image', 'inspect', tag, capture=True))[0]
        if info['Architecture'] != 'arm64' or info['Os'] != 'linux':
            raise ValueError('ARM64 Linux 이미지가 아닙니다: ' + role)
        metadata[role] = {'tag': tag, 'id': info['Id'], 'platform': 'linux/arm64'}
    # QEMU smoke 검증은 실제 Pi의 메모리·지연 검증을 대체하지 않는다.
    run('docker', 'run', '--rm', '--network', 'none', '--read-only',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m,uid=10001,gid=10001',
        '--entrypoint', 'python', images['backend'], '-c',
        'import torch; import backend.server.app; '
        'assert torch.version.cuda is None; '
        'assert torch.ones(2).sum().item() == 2')
    run('docker', 'run', '--rm', '--network', 'none', '--read-only',
        '--entrypoint', 'python', images['gateway'], '-c',
        'import gateway.app; from pathlib import Path; '
        'assert Path("frontend/static/dist/manifest.json").is_file()')
    run('docker', 'run', '--rm', '--network', 'none', '--read-only',
        '--user', '10001:10001', '--env', 'MAGI_PUBLIC_ORIGIN=https://magi.example',
        '--mount', f'type=bind,source={Path("deploy/Caddyfile").resolve()},target=/etc/caddy/Caddyfile,readonly',
        '--entrypoint', 'caddy', images['caddy'], 'validate', '--config', '/etc/caddy/Caddyfile',
        '--adapter', 'caddyfile')
    run('docker', 'image', 'save', '--output', str(output / 'magi-images.tar'), *images.values())
    for name, source in sources.items():
        shutil.copyfile(source, output / name)
    manifest = {
        'source_commit': commit, 'release': release, 'images': metadata,
        'caddy_source': CADDY, 'model': {'name': 'BAAI/bge-m3', 'revision': revision,
        'dtype': 'float32', 'dimensions': 1024, 'max_tokens': 512, 'external_read_only': True},
        'verified': ['source-ci-syntax-and-frontend', 'arm64-qemu-import-smoke'],
        'pending': ['local-python-regression', 'pi-model-load', 'pi-6GB-memory', 'database-clone-migration-restore',
                    'public-https-google-login-and-user-isolation'],
    }
    (output / 'release.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (output / 'images.txt').write_text(''.join(f'MAGI_{role.upper()}_IMAGE={tag}\n'
                                             for role, tag in images.items()), encoding='utf-8')


def finalize(output):
    expected = BASE_FILES | REPORTS
    if {path.name for path in output.iterdir()} != expected:
        raise ValueError('릴리스 파일 또는 검사 보고서가 누락되었거나 예상하지 않은 파일이 있습니다.')
    for name in REPORTS:
        json.loads((output / name).read_text(encoding='utf-8'))
    lines = [f'{sha256(output / name)}  {name}\n' for name in sorted(expected)]
    (output / 'SHA256SUMS').write_text(''.join(lines), encoding='utf-8')


def summarize_scans(output):
    """JSON 전용 출력으로 숨겨진 차단 원인을 로그에 표시하고 실패 정책을 유지한다."""
    safe = True
    for role in ROLES:
        path = output / f'{role}.vulnerabilities.json'
        try:
            report = json.loads(path.read_text(encoding='utf-8'))
            if report.get('SchemaVersion') != 2 or not isinstance(report.get('Results'), list):
                raise ValueError
        except (OSError, ValueError, AttributeError):
            print(f'{role}: 검사 보고서가 없거나 형식이 올바르지 않습니다.')
            safe = False
            continue
        findings = []
        try:
            for result in report['Results']:
                for item in result.get('Vulnerabilities') or []:
                    if item.get('Severity') == 'CRITICAL' and item.get('FixedVersion'):
                        findings.append({key: item.get(key) for key in (
                            'VulnerabilityID', 'PkgName', 'InstalledVersion', 'FixedVersion', 'Severity')})
        except (TypeError, AttributeError):
            print(f'{role}: 검사 보고서의 취약점 목록이 올바르지 않습니다.')
            safe = False
            continue
        print(f'{role}: 수정 가능한 CRITICAL 취약점 {len(findings)}건')
        for finding in findings:
            # 외부 보고서의 개행·명령 문자열이 로그 명령으로 해석되지 않게 JSON으로 출력한다.
            print(json.dumps(finding, ensure_ascii=True))
        safe &= not findings
    return bool(safe)


def verify(output, check_images=False):
    expected = BASE_FILES | REPORTS
    entries = {}
    for line in (output / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_.-]+)', line)
        if not match or match[2] not in expected or match[2] in entries:
            raise ValueError('체크섬 목록이 올바르지 않습니다.')
        entries[match[2]] = match[1]
    if set(entries) != expected:
        raise ValueError('체크섬 목록에 필수 파일이 누락되었습니다.')
    for name, expected_hash in entries.items():
        path = output / name
        if path.is_symlink() or not path.is_file() or sha256(path) != expected_hash:
            raise ValueError('릴리스 파일 검증에 실패했습니다: ' + name)
    if check_images:
        manifest = json.loads((output / 'release.json').read_text(encoding='utf-8'))
        for role in ROLES:
            image = manifest['images'][role]
            info = json.loads(run('docker', 'image', 'inspect', image['tag'], capture=True))[0]
            if info['Id'] != image['id'] or info['Architecture'] != 'arm64' or info['Os'] != 'linux':
                raise ValueError('로드된 이미지가 릴리스와 일치하지 않습니다: ' + role)


def publish(output, repository, images_file):
    """운영 비밀 없이 CI의 레지스트리 인증을 사용하고 전체 게시 성공 후 주소를 기록한다."""
    repository = repository.lower()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]*/[a-z0-9][a-z0-9_.-]*', repository):
        raise ValueError('게시 대상은 GitHub owner/repository 형식이어야 합니다.')
    if images_file.exists() or images_file.resolve().is_relative_to(output.resolve()):
        raise ValueError('이미지 주소 파일은 릴리스 밖의 새 경로여야 합니다.')
    verify(output, check_images=True)
    if not summarize_scans(output):
        raise ValueError('보안 검사를 통과하지 못한 릴리스는 게시하지 않습니다.')
    manifest = json.loads((output / 'release.json').read_text(encoding='utf-8'))
    release = manifest['release']
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,127}', release):
        raise ValueError('릴리스 이름은 Docker 태그 형식이어야 합니다.')
    lines = []
    for role in ROLES:
        image = manifest['images'][role]
        target = f'ghcr.io/{repository}-{role}'
        tag = f'{target}:{release}'
        run('docker', 'image', 'tag', image['tag'], tag)
        run('docker', 'image', 'push', tag)
        descriptor = json.loads(run('docker', 'buildx', 'imagetools', 'inspect', tag,
                                    '--format', '{{json .Manifest}}', capture=True))
        digest = descriptor['digest']
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
            raise ValueError('레지스트리 digest가 올바르지 않습니다: ' + role)
        reference = f'{target}@{digest}'
        remote = json.loads(run('docker', 'buildx', 'imagetools', 'inspect', reference,
                                '--raw', capture=True))
        if remote.get('config', {}).get('digest') != image['id']:
            raise ValueError('게시한 이미지가 검사한 이미지와 다릅니다: ' + role)
        lines.append(f'MAGI_{role.upper()}_IMAGE={reference}\n')
    images_file.parent.mkdir(parents=True, exist_ok=True)
    images_file.write_text(''.join(lines), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'finalize', 'verify', 'check-inputs', 'summarize-scans', 'publish'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--release')
    parser.add_argument('--model-revision')
    parser.add_argument('--check-images', action='store_true')
    parser.add_argument('--repository')
    parser.add_argument('--images-file', type=Path)
    args = parser.parse_args()
    if args.action == 'check-inputs':
        release_inputs()
        return
    if args.output is None:
        parser.error('이 작업에는 --output이 필요합니다.')
    if args.action == 'summarize-scans':
        raise SystemExit(0 if summarize_scans(args.output) else 1)
    if args.action == 'publish':
        if not args.repository or args.images_file is None:
            parser.error('publish에는 --repository와 --images-file이 필요합니다.')
        publish(args.output, args.repository, args.images_file)
        return
    if args.action == 'build':
        if not args.release or not args.model_revision:
            parser.error('build에는 --release와 --model-revision이 필요합니다.')
        build(args.output, args.release, args.model_revision)
    elif args.action == 'finalize':
        finalize(args.output)
    else:
        verify(args.output, args.check_images)


if __name__ == '__main__':
    main()
