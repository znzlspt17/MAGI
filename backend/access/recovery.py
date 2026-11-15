"""종료된 실행의 정리만 재시도한다. 제공자 호출은 재실행하지 않는다."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from protocol.logging import get_logger
import asyncio
from contextlib import suppress

from backend.access.context import ACTOR
from backend.server.execution_history import ExecutionHistory


LOGGER = get_logger('backend.server')


@dataclass(frozen=True)
class Execution:
    ident: str
    execution_id: str
    generation: int
    initial: tuple | None

    @classmethod
    def from_job(cls, job):
        initial = job.get('_initial_reservation')
        return cls(job['id'], job['execution_id'], job['execution_generation'],
                   tuple(initial) if initial else None)


@dataclass(frozen=True)
class Failure:
    execution: Execution
    entered: bool
    unused: tuple | None


class WorkerRecovery:
    def __init__(self, service):
        self.service = service
        self.pending = {}
        self.lock = asyncio.Lock()
        self.retry_lock = asyncio.Lock()
        self.stopped = asyncio.Event()
        self.task = None

    async def record(self, failure):
        async with self.lock:
            self.pending[failure.execution] = failure
        await self.retry()
        async with self.lock:
            if self.pending and not self.stopped.is_set() and self.task is None:
                self.task = asyncio.create_task(self._loop(), name='recovery')

    async def _loop(self):
        while not self.stopped.is_set():
            try:
                await asyncio.wait_for(self.stopped.wait(), timeout=5)
            except asyncio.TimeoutError:
                await self.retry()

    async def close(self):
        self.stopped.set()
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task

    async def retry(self):
        # 2026-11-13: 중지 응답은 앞서 진행 중인 복구까지 완료된 뒤 반환한다.
        await self.retry_lock.acquire()
        # 요청·작업자 문맥으로 정리 권한이나 비용 계측을 상속하지 않는다.
        actor_token = ACTOR.set(None)
        try:
            async with self.lock:
                failures = list(self.pending.values())
            for failure in failures:
                try:
                    await self._repair(failure)
                except Exception as exc:
                    LOGGER.error('worker cleanup pending job_id=%s execution_id=%s exception_type=%s',
                                 failure.execution.ident, failure.execution.execution_id, type(exc).__name__)
                else:
                    async with self.lock:
                        if self.pending.get(failure.execution) is failure:
                            self.pending.pop(failure.execution)
        finally:
            ACTOR.reset(actor_token)
            self.retry_lock.release()

    async def _repair(self, failure):
        service = self.service
        manager = service.manager
        execution = failure.execution
        snapshot = None
        async with manager.job_lock(execution.ident):
            job = manager.jobs.get(execution.ident)
            if job is not None and (job.get('execution_id') != execution.execution_id
                                    or job.get('execution_generation') != execution.generation):
                return
            async with service.store.transaction() as c:
                lease = await (await c.execute('SELECT * FROM execution_leases WHERE execution_id=%s AND generation=%s FOR UPDATE',
                                  (execution.execution_id,execution.generation))).fetchone()
                row = await (await c.execute('SELECT data FROM jobs WHERE id=%s', (execution.ident,))).fetchone()
                if (not row or row['data'].get('execution_id') != execution.execution_id
                    or row['data'].get('execution_generation') != execution.generation
                    or not lease or lease['phase'] not in {'queued','running','recovery'}):
                    return
                updated = dict(row['data'])
                updated.pop('_initial_reservation',None)
                updated.update(status='interrupted' if lease['stopping'] else 'error',
                               message='작업이 중지되었습니다.' if lease['stopping'] else '작업 실행에 실패했습니다. 입력과 기록은 보존됩니다.',
                               updated_at=datetime.now(UTC).isoformat())
                await service.store._save_job(c,updated)
                await c.execute('UPDATE executions SET data=data || %s WHERE id=%s AND job_id=%s',
                          (service.store._json({'status':updated['status'],'message':updated['message']}),execution.execution_id,execution.ident))
                if failure.unused:
                    unused = await (await c.execute('SELECT called_at FROM cost_calls WHERE id=%s', (failure.unused[0],))).fetchone()
                    if unused and unused['called_at'] is None:
                        await service.access.settle(failure.unused[0],Decimal(0),generation=execution.generation,execution_id=execution.execution_id)
                await c.execute("UPDATE cost_calls SET state='uncertain' WHERE execution_id=%s AND execution_generation=%s AND state='reserved'",
                          (execution.execution_id,execution.generation))
                await service.access.finish(execution.ident,execution.generation,execution.execution_id)
            if job is None:
                manager.jobs[execution.ident] = updated
                job = updated
            else:
                job.clear()
                job.update(updated)
            try:
                await ExecutionHistory(await manager.workspace.documents(execution.ident)).terminal(
                    execution.execution_id, 'error', updated['message'])
            except Exception as exc:
                LOGGER.warning('worker failure history unavailable exception_type=%s', type(exc).__name__)
            snapshot = manager._snapshot(job)
        if snapshot is not None:
            manager._notify(snapshot)
