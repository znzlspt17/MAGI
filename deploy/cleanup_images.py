"""게시가 완료된 latest 이미지 외의 GHCR 버전을 정리한다."""

import json
import subprocess
from urllib.parse import quote

from deploy.artifacts import ROLES


def api(path, method='GET'):
    result = subprocess.run(
        ['gh', 'api', '--method', method, path],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def cleanup(repository, owner_type, manifest):
    owner, repo = repository.lower().split('/')
    if owner_type not in ('User', 'Organization'):
        raise ValueError('지원하지 않는 패키지 소유자 유형입니다.')
    scope = 'orgs' if owner_type == 'Organization' else 'users'
    pending = []
    # 모든 패키지의 latest와 게시 digest를 확인한 후에만 삭제를 시작한다.
    for role in ROLES:
        package = quote(f'{repo}-{role}', safe='')
        path = f'/{scope}/{owner}/packages/container/{package}/versions'
        versions = []
        page = 1
        while True:
            batch = api(f'{path}?per_page=100&page={page}')
            versions.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        latest = [v for v in versions if 'latest' in v['metadata']['container']['tags']]
        if len(latest) != 1 or latest[0]['name'] != manifest['published'][role]['digest']:
            raise ValueError('latest가 게시한 릴리스와 일치하지 않습니다: ' + role)
        pending.extend((path, v['id']) for v in versions if v['id'] != latest[0]['id'])
    for path, version_id in pending:
        api(f'{path}/{version_id}', method='DELETE')
    print(f'이전 이미지 버전 {len(pending)}개 정리 완료')
