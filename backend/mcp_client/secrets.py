"""MCP 인증정보를 작업 상태와 분리해 암호화한다."""

import json
import os
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken
from backend.access.context import AccessError


def _fernet():
    # 2026-11-03: 비밀이 없으면 연결 기능을 중단하고 임시 키로 우회하지 않는다.
    try:
        key = os.environ.get("MAGI_MCP_ENCRYPTION_KEY", "").encode("ascii")
        return Fernet(key)
    except (ValueError, UnicodeError):
        raise AccessError("MCP 암호화 키 설정을 확인하세요.", "unavailable") from None


def seal(owner_id: str, connection_id: str, data: dict) -> str:
    raw = json.dumps({"owner_id": owner_id, "connection_id": connection_id, "data": data},
                     ensure_ascii=False, separators=(",", ":")).encode()
    return _fernet().encrypt(raw).decode("ascii")


def unseal(owner_id: str, connection_id: str, ciphertext: str | None) -> dict:
    if not ciphertext:
        return {}
    try:
        value = json.loads(_fernet().decrypt(ciphertext.encode("ascii")))
        if value.get("owner_id") != owner_id or value.get("connection_id") != connection_id or not isinstance(value.get("data"), dict):
            raise ValueError()
        return value["data"]
    except (InvalidToken, ValueError, TypeError, UnicodeError):
        raise AccessError("MCP 인증정보를 읽을 수 없습니다. 연결을 다시 설정하세요.", "unavailable") from None


def request_fingerprint(method: str, params: dict) -> str:
    # 2026-11-03: 중복 방지 저장소에는 평문 인증값이나 무키 해시를 남기지 않는다.
    _fernet()
    key = os.environ["MAGI_MCP_ENCRYPTION_KEY"].encode("ascii")
    raw = json.dumps([method, params], sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hmac.new(key, raw, hashlib.sha256).hexdigest()
