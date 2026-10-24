"""ARM64 릴리스를 검증하고, 검사한 동일 이미지를 GHCR에 게시한다."""

import json
from pathlib import Path
import re
import subprocess


CADDY = 'caddy:2-alpine@sha256:d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f'
ROLES = ('gateway', 'backend', 'caddy')
INPUT_FILES = ('compose.portainer.yaml', 'Caddyfile')


def run(*args, capture=False, **kwargs):
    result = subprocess.run(args, check=True, text=True, capture_output=capture, **kwargs)
    return result.stdout.strip() if capture else None


def release_inputs():
    # Git에서 제외한 로컬 문서는 릴리스 입력으로 요구하거나 복사하지 않는다.
    sources = {name: Path('deploy') / name for name in INPUT_FILES}
    missing = [str(path) for path in sources.values() if not path.is_file() or path.is_symlink()]
    if missing:
        raise ValueError('배포 필수 파일이 누락되었거나 일반 파일이 아닙니다: ' + ', '.join(missing))
    return sources


def smoke(output, release):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,127}', release):
        raise ValueError('릴리스 이름은 Docker 태그 형식이어야 합니다.')
    release_inputs()
    if output.exists() and any(output.iterdir()):
        raise ValueError('기존 릴리스를 덮어쓰지 않도록 빈 출력 경로를 지정하세요.')
    output.mkdir(parents=True, exist_ok=True)
    commit = run('git', 'rev-parse', 'HEAD', capture=True)
    images = {role: f'magi-{role}:{release}' for role in ROLES}
    run('docker', 'pull', '--platform', 'linux/arm64', CADDY)
    run('docker', 'image', 'tag', CADDY, images['caddy'])
    metadata = {}
    for role, tag in images.items():
        info = json.loads(run('docker', 'image', 'inspect', tag, capture=True))[0]
        if info['Architecture'] != 'arm64' or info['Os'] != 'linux':
            raise ValueError('ARM64 Linux 이미지가 아닙니다: ' + role)
        metadata[role] = {'tag': tag, 'id': info['Id'], 'platform': 'linux/arm64'}
    # QEMU smoke 검증은 실제 Pi의 메모리·지연 검증을 대체하지 않는다.
    run('docker', 'run', '--rm', '--init', '--network', 'none', '--read-only',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--user', '10001:10001',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m,uid=10001,gid=10001',
        '--entrypoint', 'python', images['backend'], '-c',
        'import torch; import backend.server.app; '
        'from backend.knowledge.setup import load_migrations; assert load_migrations(); '
        'assert torch.version.cuda is None; '
        'assert torch.ones(2).sum().item() == 2')
    run('docker', 'run', '--rm', '--init', '--network', 'none', '--read-only',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true', '--user', '10001:10001',
        '--entrypoint', 'python', images['gateway'], '-c',
        'import gateway.app; from pathlib import Path; '
        'assert Path("frontend/static/dist/manifest.json").is_file()')
    run('docker', 'run', '--rm', '--init', '--network', 'none', '--read-only',
        '--cap-drop', 'ALL', '--cap-add', 'NET_BIND_SERVICE', '--security-opt', 'no-new-privileges:true',
        '--user', '10001:10001', '--env', 'PUBLIC_ORIGIN=https://magi.example',
        '--mount', f'type=bind,source={Path("deploy/Caddyfile").resolve()},target=/etc/caddy/Caddyfile,readonly',
        '--entrypoint', 'caddy', images['caddy'], 'validate', '--config', '/etc/caddy/Caddyfile',
        '--adapter', 'caddyfile')
    manifest = {
        'source_commit': commit, 'release': release, 'images': metadata,
        'caddy_source': CADDY, 'model': {'name': 'BAAI/bge-m3',
        'dtype': 'float32', 'dimensions': 1024, 'max_tokens': 512, 'external_read_only': True},
        'verified': ['source-ci-syntax-and-frontend', 'arm64-qemu-import-smoke'],
        'pending': ['local-python-regression', 'pi-model-load', 'pi-6GB-memory', 'database-auto-migration-backup-restore',
                    'public-https-google-login-and-user-isolation'],
    }
    (output / 'release.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


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
                if not isinstance(result, dict):
                    raise ValueError
                vulnerabilities = result.get('Vulnerabilities')
                if vulnerabilities is None:
                    vulnerabilities = []
                if not isinstance(vulnerabilities, list):
                    raise ValueError
                for item in vulnerabilities:
                    if not isinstance(item, dict) or not isinstance(item.get('Severity'), str):
                        raise ValueError
                    if not isinstance(item.get('FixedVersion', ''), str):
                        raise ValueError
                    if item.get('Severity') == 'CRITICAL' and item.get('FixedVersion'):
                        findings.append({key: item.get(key) for key in (
                            'VulnerabilityID', 'PkgName', 'InstalledVersion', 'FixedVersion', 'Severity')})
        except (TypeError, ValueError, AttributeError):
            print(f'{role}: 검사 보고서의 취약점 목록이 올바르지 않습니다.')
            safe = False
            continue
        print(f'{role}: 수정 가능한 CRITICAL 취약점 {len(findings)}건')
        for finding in findings:
            # 외부 보고서의 개행·명령 문자열이 로그 명령으로 해석되지 않게 JSON으로 출력한다.
            print(json.dumps(finding, ensure_ascii=True))
        safe &= not findings
    return bool(safe)


def verify_images(manifest):
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
    if not summarize_scans(output):
        raise ValueError('보안 검사를 통과하지 못한 릴리스는 게시하지 않습니다.')
    manifest = json.loads((output / 'release.json').read_text(encoding='utf-8'))
    verify_images(manifest)
    release = manifest['release']
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,127}', release):
        raise ValueError('릴리스 이름은 Docker 태그 형식이어야 합니다.')
    lines = []
    published = {}
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
        published[role] = {'tag': tag, 'digest': digest, 'reference': reference}
        lines.append(f'{role.upper()}_IMAGE={target}:latest\n')
    # 모든 이미지의 릴리스 태그를 확인한 뒤에만 latest를 갱신한다.
    # GHCR의 여러 태그 갱신은 원자적이지 않으므로 중간 실패를 그대로 전달한다.
    for role in ROLES:
        latest = f'ghcr.io/{repository}-{role}:latest'
        run('docker', 'image', 'tag', manifest['images'][role]['tag'], latest)
        run('docker', 'image', 'push', latest)
        descriptor = json.loads(run('docker', 'buildx', 'imagetools', 'inspect', latest,
                                    '--format', '{{json .Manifest}}', capture=True))
        if descriptor.get('digest') != published[role]['digest']:
            raise ValueError('latest가 검증한 릴리스와 다릅니다: ' + role)
    manifest['published'] = published
    (output / 'release.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    images_file.parent.mkdir(parents=True, exist_ok=True)
    images_file.write_text(''.join(lines), encoding='utf-8')
