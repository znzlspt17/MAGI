"""부가 작업의 완료 저장까지 실행 활동으로 추적한다."""
from functools import wraps


def tracked(function):
    """표시 상태가 완료로 바뀐 뒤의 저장까지 실제 활동으로 추적한다."""

    @wraps(function)
    def wrapped(self, ident, *args, **kwargs):
        with self.lock:
            self.get(ident)
            self._activities[ident] = self._activities.get(ident, 0) + 1
        try:
            return function(self, ident, *args, **kwargs)
        finally:
            with self.lock:
                self._activities[ident] -= 1

    return wrapped


