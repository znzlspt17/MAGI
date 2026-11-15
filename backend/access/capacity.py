"""작업과 동기 AI 요청이 공유하는 실행 용량과 유지보수 진입 보호."""

from contextlib import asynccontextmanager
import asyncio

from backend.access.context import AccessError


MAX_PARALLEL = 100
MAX_ADMITTED = 200


class ExecutionCapacity:
    def __init__(self):
        self.condition = asyncio.Condition()
        self.active = 0
        self.maintaining = False

    async def check_admission(self):
        async with self.condition:
            if self.maintaining:
                raise AccessError('유지보수 중입니다. 잠시 후 다시 시도하세요.', 'capacity')

    @asynccontextmanager
    async def slot(self, *, blocking):
        # 2026-11-13: 실행 대기 중에는 이벤트 루프를 점유하지 않는다.
        async with self.condition:
            available = lambda: self.active < MAX_PARALLEL and not self.maintaining
            if blocking:
                await self.condition.wait_for(available)
            elif not available():
                raise AccessError('동시 실행 한도에 도달했습니다. 잠시 후 다시 시도하세요.', 'capacity')
            self.active += 1
        try:
            yield
        finally:
            async with self.condition:
                self.active -= 1
                self.condition.notify_all()

    @asynccontextmanager
    async def maintenance(self):
        async with self.condition:
            if self.active or self.maintaining:
                raise AccessError('실행이 끝난 뒤 유지보수를 시작하세요.', 'capacity')
            self.maintaining = True
        try:
            yield
        finally:
            async with self.condition:
                self.maintaining = False
                self.condition.notify_all()
