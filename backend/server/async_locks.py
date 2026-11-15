"""동일 태스크의 중첩 명령을 지원하는 비동기 잠금."""

import asyncio


class AsyncRLock:
    """2026-11-13: 스레드 식별이 아닌 태스크 식별로 재진입을 제한한다."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._owner = None
        self._depth = 0

    async def acquire(self):
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("비동기 태스크에서만 잠금을 사용할 수 있습니다.")
        if self._owner is task:
            self._depth += 1
            return True
        await self._lock.acquire()
        self._owner, self._depth = task, 1
        return True

    def release(self):
        if self._owner is not asyncio.current_task():
            raise RuntimeError("잠금을 보유한 태스크만 해제할 수 있습니다.")
        self._depth -= 1
        if not self._depth:
            self._owner = None
            self._lock.release()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *_args):
        self.release()
