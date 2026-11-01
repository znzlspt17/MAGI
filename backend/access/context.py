"""스레드 간 암묵적으로 공유하지 않는 요청·비용 문맥."""

from contextvars import ContextVar
from typing import Any

ACTOR: ContextVar[dict[str, Any] | None] = ContextVar('actor', default=None)
TRANSACTION: ContextVar[tuple[Any, Any, str] | None] = ContextVar('transaction', default=None)
DEFERRED: ContextVar[list[tuple[str, str, object]] | None] = ContextVar('deferred', default=None)
ADMISSION: ContextVar[tuple[str, str] | None] = ContextVar('admission', default=None)


class AccessError(ValueError):
    def __init__(self, message, code='forbidden'):
        super().__init__(message)
        self.code = code


def user_id():
    actor = ACTOR.get()
    return actor['id'] if actor else None
