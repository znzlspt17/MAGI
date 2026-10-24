"""종료된 실행의 정리만 재시도한다. 제공자 호출은 재실행하지 않는다."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import logging
import threading

from backend.access.context import ACTOR
from backend.server.execution_history import ExecutionHistory


LOGGER = logging.getLogger('backend.server')


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
        self.lock = threading.Lock()
        self.retry_lock = threading.Lock()
        self.stopped = threading.Event()
        self.thread = None

    def record(self, failure):
        with self.lock:
            self.pending[failure.execution] = failure
        self.retry()
        with self.lock:
            if self.pending and not self.stopped.is_set() and self.thread is None:
                self.thread = threading.Thread(target=self._loop, name='recovery', daemon=True)
                self.thread.start()

    def _loop(self):
        while not self.stopped.wait(5):
            self.retry()

    def close(self):
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=1)

    def retry(self):
        if not self.retry_lock.acquire(blocking=False):
            return
        # 요청·작업자 문맥으로 정리 권한이나 비용 계측을 상속하지 않는다.
        actor_token = ACTOR.set(None)
        try:
            with self.lock:
                failures = list(self.pending.values())
            for failure in failures:
                try:
                    self._repair(failure)
                except Exception as exc:
                    LOGGER.error('worker cleanup pending job_id=%s execution_id=%s exception_type=%s',
                                 failure.execution.ident, failure.execution.execution_id, type(exc).__name__)
                else:
                    with self.lock:
                        if self.pending.get(failure.execution) is failure:
                            self.pending.pop(failure.execution)
        finally:
            ACTOR.reset(actor_token)
            self.retry_lock.release()

    def _repair(self, failure):
        service = self.service
        manager = service.manager
        execution = failure.execution
        snapshot = None
        with manager.lock:
            job = manager.jobs.get(execution.ident)
            if job is not None and (job.get('execution_id') != execution.execution_id
                                    or job.get('execution_generation') != execution.generation):
                return
            with service.store.transaction() as c:
                lease = c.execute('SELECT * FROM execution_leases WHERE execution_id=%s AND generation=%s FOR UPDATE',
                                  (execution.execution_id,execution.generation)).fetchone()
                row = c.execute('SELECT data FROM jobs WHERE id=%s', (execution.ident,)).fetchone()
                if (not row or row['data'].get('execution_id') != execution.execution_id
                    or row['data'].get('execution_generation') != execution.generation
                    or not lease or lease['phase'] not in {'queued','running','recovery'}):
                    return
                updated = dict(row['data'])
                updated.pop('_initial_reservation',None)
                updated.update(status='interrupted' if lease['stopping'] else 'error',
                               message='작업이 중지되었습니다.' if lease['stopping'] else '작업 실행에 실패했습니다. 입력과 기록은 보존됩니다.',
                               updated_at=datetime.now(UTC).isoformat())
                service.store._save_job(c,updated)
                c.execute('UPDATE executions SET data=data || %s WHERE id=%s AND job_id=%s',
                          (service.store._json({'status':updated['status'],'message':updated['message']}),execution.execution_id,execution.ident))
                if failure.unused:
                    unused = c.execute('SELECT called_at FROM cost_calls WHERE id=%s', (failure.unused[0],)).fetchone()
                    if unused and unused['called_at'] is None:
                        service.access.settle(failure.unused[0],Decimal(0),generation=execution.generation,execution_id=execution.execution_id)
                c.execute("UPDATE cost_calls SET state='uncertain' WHERE execution_id=%s AND execution_generation=%s AND state='reserved'",
                          (execution.execution_id,execution.generation))
                service.access.finish(execution.ident,execution.generation,execution.execution_id)
            if job is None:
                manager.jobs[execution.ident] = updated
                job = updated
            else:
                job.clear()
                job.update(updated)
            try:
                ExecutionHistory(manager.workspace.documents(execution.ident)).terminal(
                    execution.execution_id, 'error', updated['message'])
            except Exception as exc:
                LOGGER.warning('worker failure history unavailable exception_type=%s', type(exc).__name__)
            snapshot = manager._snapshot(job)
        if snapshot is not None:
            manager._notify(snapshot)
