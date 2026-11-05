"""문서 원문과 근거의 동일성을 확인하는 해시."""

import hashlib


def source_key(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
