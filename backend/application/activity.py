"""부가 작업의 완료 저장까지 실행 활동으로 추적한다."""
from functools import wraps


def tracked(function):
    """표시 상태가 완료로 바뀐 뒤의 저장까지 실제 활동으로 추적한다."""

    @wraps(function)
    async def wrapped(self, ident, *args, **kwargs):
        # 2026-11-13: 조회 대기 중에도 정리 대상에서 보호하되 전역 잠금은 메모리 변경에만 사용한다.
        async with self.lock:
            self._activities[ident] = self._activities.get(ident, 0) + 1
        try:
            await self.get(ident)
            return await function(self, ident, *args, **kwargs)
        finally:
            async with self.lock:
                self._activities[ident] -= 1

    return wrapped


