"""종료된 실행의 정리만 재시도한다. 제공자 호출은 재실행하지 않는다."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import logging
import threading

from backend.access.context import ACTOR, METER
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
        return cls(job['id'], job['execution_id'], job['lease_generation'],
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
                self.thread = threading.Thread(target=self._loop, name='magi-recovery', daemon=True)
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
        meter_token = METER.set(None)
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
            METER.reset(meter_token)
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
                                    or job.get('lease_generation') != execution.generation):
                return
            with service.store.transaction() as c:
                lease = service.access.lease(c)
                row = c.execute('SELECT data FROM magi_jobs WHERE id=%s', (execution.ident,)).fetchone()
                if (not row or row['data'].get('execution_id') != execution.execution_id
                    or row['data'].get('lease_generation') != execution.generation):
                    return
                if lease['job_id'] != execution.ident or lease['generation'] != execution.generation:
                    # COMMIT 응답만 잃은 경우 영구 기록을 메모리에 반영한다.
                    if row['data'].get('status') != 'error':
                        return
                    updated = dict(row['data'])
                else:
                    updated = dict(row['data'] if job is None else job)
                    updated.pop('_initial_reservation', None)
                    updated.update(status='error', message='작업 실행에 실패했습니다. 입력과 기록은 보존됩니다.',
                                   updated_at=datetime.now(UTC).isoformat())
                    resume = updated.get('resume_status')
                    if not failure.entered and manager._can_resume_action(updated['action'], resume):
                        updated['recoverable_status'] = resume
                    # 메모리 상태는 COMMIT이 성공한 뒤에만 바꾼다.
                    service.store._save_job(c, updated)
                    c.execute('UPDATE magi_executions SET data=data || %s WHERE id=%s AND job_id=%s',
                              (service.store._json({'status': 'error', 'message': updated['message']}),
                               execution.execution_id, execution.ident))
                    if failure.unused:
                        service.access.settle(failure.unused[0], Decimal(0))
                    if failure.entered:
                        c.execute("UPDATE magi_service_lease SET phase='recovery',deadline=NULL WHERE singleton=1")
                    else:
                        service.access.finish(execution.ident, execution.generation)
            if job is None:
                manager.jobs[execution.ident] = updated
                job = updated
            else:
                job.clear()
                job.update(updated)
            manager._export_job_locked(job)
            try:
                ExecutionHistory(manager._job_root(execution.ident)).terminal(
                    execution.execution_id, 'error', updated['message'])
            except Exception as exc:
                LOGGER.warning('worker failure history unavailable exception_type=%s', type(exc).__name__)
            snapshot = manager._snapshot(job)
        if snapshot is not None:
            manager._notify(snapshot)
