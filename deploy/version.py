"""배포 이미지의 식별자를 제품 버전과 CI 빌드 번호로 만든다."""

from pathlib import Path
import re
import tomllib


def release_id(project_file: Path, build: str, attempt: str) -> str:
    # 2026-11-06: 같은 제품 버전을 재빌드해도 이미지 태그가 충돌하지 않아야 한다.
    with project_file.open('rb') as source:
        version = tomllib.load(source)['project']['version']
    component = r'(?:0|[1-9][0-9]*)'
    if not isinstance(version, str) or not re.fullmatch(rf'{component}\.{component}\.{component}', version):
        raise ValueError('제품 버전은 MAJOR.MINOR.PATCH 형식이어야 합니다.')
    if not re.fullmatch(r'[1-9][0-9]*', build) or not re.fullmatch(r'[1-9][0-9]*', attempt):
        raise ValueError('빌드 번호와 재실행 횟수는 양의 정수여야 합니다.')
    result = f'v{version}-build.{build}.{attempt}'
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,127}', result):
        raise ValueError('릴리스 이름이 Docker 태그 형식에 맞지 않습니다.')
    return result
