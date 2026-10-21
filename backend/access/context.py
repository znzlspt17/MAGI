"""스레드 간 암묵적으로 공유하지 않는 요청·비용 문맥."""

from contextvars import ContextVar

ACTOR = ContextVar('actor', default=None)
TRANSACTION = ContextVar('transaction', default=None)
DEFERRED = ContextVar('deferred', default=None)
METER = ContextVar('meter', default=None)


class AccessError(ValueError):
    def __init__(self, message, code='forbidden'):
        super().__init__(message)
        self.code = code


def user_id():
    actor = ACTOR.get()
    return actor['id'] if actor else None
