"""이전 저장 형식을 빈 작업으로 오인하지 않도록 쓰기 전에 확인한다."""

from pathlib import Path
from backend.knowledge.config import KnowledgeError


PENDING_FILE = '.prefix-transition-pending'


def require_current(root):
    root = Path(root).absolute()
    old_default = {'web_data': 'magi_web_data', 'output': 'magi_output'}.get(root.name)
    if old_default and (root.parent / old_default).exists():
        raise KnowledgeError('이전 기본 폴더가 있습니다. python -m backend.knowledge.rename 명령으로 먼저 전환하세요.')
    if not root.exists():
        return
    if (root / PENDING_FILE).exists():
        raise KnowledgeError('파일 전환이 완료되지 않았습니다. 전환 명령을 재실행하세요.')
    folders = [root]
    folders.extend(p for p in root.iterdir() if p.is_dir() and not p.is_symlink())
    if any((folder / 'state/magi_state.json').exists() for folder in folders):
        raise KnowledgeError('이전 체크포인트가 있습니다. python -m backend.knowledge.rename 명령으로 먼저 전환하세요.')


def require_current_model(root):
    if root is not None:
        root = Path(root)
        if (root / 'magi_model_revision.json').exists() or (root / PENDING_FILE).exists():
            raise KnowledgeError('이전 또는 전환 중인 모델 파일입니다. 먼저 접두사 전환 명령을 완료하세요.')

