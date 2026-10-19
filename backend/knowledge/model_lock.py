"""동일 PC의 백엔드와 재색인 프로세스가 모델 메모리를 중복 점유하지 않게 한다."""

import os
from pathlib import Path
import tempfile
import threading

from backend.knowledge.config import KnowledgeError

_guard = threading.Lock()
_owner = None


def acquire(owner, path=None):
    global _owner
    with _guard:
        if _owner is owner:
            return
        if _owner is not None:
            raise KnowledgeError("다른 임베딩 실행이 모델을 사용 중입니다.")
        path = Path(path) if path else Path(tempfile.gettempdir()) / "magi-local-embedding.lock"
        stream = path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                if not stream.read(1):
                    stream.write(b"0"); stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            stream.close()
            raise KnowledgeError("다른 임베딩 프로세스가 모델을 사용 중입니다.") from None
        owner._process_lock = stream
        _owner = owner


def release(owner):
    global _owner
    with _guard:
        if _owner is owner:
            owner._process_lock.close()
            _owner = None
