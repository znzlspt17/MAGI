"""작업과 동기 AI 요청이 공유하는 실행 용량과 유지보수 진입 보호."""

from contextlib import contextmanager
import threading

from backend.access.context import AccessError


MAX_PARALLEL = 2


class ExecutionCapacity:
    def __init__(self):
        self.condition = threading.Condition()
        self.active = 0
        self.maintaining = False

    def check_admission(self):
        with self.condition:
            if self.maintaining:
                raise AccessError('유지보수 중입니다. 잠시 후 다시 시도하세요.', 'capacity')

    @contextmanager
    def slot(self, *, blocking):
        with self.condition:
            available = lambda: self.active < MAX_PARALLEL and not self.maintaining
            if blocking:
                self.condition.wait_for(available)
            elif not available():
                raise AccessError('동시 실행 한도에 도달했습니다. 잠시 후 다시 시도하세요.', 'capacity')
            self.active += 1
        try:
            yield
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()

    @contextmanager
    def maintenance(self):
        with self.condition:
            if self.active or self.maintaining:
                raise AccessError('실행이 끝난 뒤 유지보수를 시작하세요.', 'capacity')
            self.maintaining = True
        try:
            yield
        finally:
            with self.condition:
                self.maintaining = False
                self.condition.notify_all()
