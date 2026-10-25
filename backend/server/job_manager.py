"""웹 작업의 접수·예약·실행. 실행 상태는 LangGraph에서만 조회한다."""

from __future__ import annotations

import copy
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

from backend.access.context import ACTOR, DEFERRED, ADMISSION
from backend.engine import Engine
from backend.server.cleanup import Cleanup, CleanupConflict, synchronized, tracked
from backend.server.diagnostics import diagnose_exception, safe_user_error
from backend.server.execution_history import ExecutionHistory

LOGGER = logging.getLogger("backend.server")
_ID = re.compile(r"[0-9a-f]{32}\Z")
_ACTIVE = {"queued", "running"}


class JobManager:
    def __init__(self, knowledge, *, engine_factory=Engine, on_change=None):
        self.knowledge, self.engine_factory, self.on_change = (
            knowledge,
            engine_factory,
            on_change,
        )
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="workflow")
        self._futures, self._activities = {}, {}
        self.closed = False
        from backend.server.workspace import Workspace

        self.workspace = Workspace(
            knowledge, engine_factory, self.lock, self._activities
        )
        self.jobs = {j["id"]: j for j in knowledge.store.jobs()}
        self._next_order = max(
            (j.get("order", 0) for j in self.jobs.values()), default=0
        )
        self.cleanup = Cleanup(self)
        self.cleanup.recover()
        for job in self.jobs.values():
            if job["status"] in _ACTIVE:
                job.update(
                    status="interrupted",
                    message="실행이 중단되었습니다. 명시적으로 재개해주세요.",
                )
                knowledge.store.save_job(job)
                ExecutionHistory(
                    self.workspace.documents(job["id"])
                ).interrupt_execution(job.get("execution_id"))

    def close(self):
        self.closed = True
        self.executor.shutdown(wait=True, cancel_futures=True)
        if getattr(self, "public_service", None):
            self.public_service.recovery.close()
        self.knowledge.close()

    @synchronized
    def create(self, request, provider=None, project_id=None, decision_reuse=None):
        self._require_open()
        if (
            sum(j.get("status") in {"queued", "running"} for j in self.jobs.values())
            >= 20
        ):
            raise CleanupConflict("작업 대기열이 가득 찼습니다.")
        if not isinstance(request, str) or not request.strip() or len(request) > 20000:
            raise ValueError("개발 요청을 확인하세요.")
        if provider not in {None, "openai"}:
            raise ValueError("지원하지 않는 모델 제공자입니다.")
        if project_id is not None and (
            not isinstance(project_id, str) or not _ID.fullmatch(project_id)
        ):
            raise ValueError("프로젝트 식별값을 확인하세요.")
        if decision_reuse and not project_id:
            raise ValueError("공통 결정의 프로젝트를 선택하세요.")
        if decision_reuse is not None and not isinstance(decision_reuse, list):
            raise ValueError("공통 결정 선택은 목록이어야 합니다.")
        self._next_order += 1
        ident, now = (ADMISSION.get() or (uuid4().hex, None))[0], _utc_now()
        job = dict(
            id=ident,
            project_id=project_id or ident,
            owner_id=ACTOR.get()["id"] if ACTOR.get() else None,
            provider="openai",
            request=request.strip(),
            status="queued",
            message="작업 대기 중",
            action="generate",
            created_at=now,
            updated_at=now,
            queued_at=now,
            order=self._next_order,
            queue_order=self._next_order,
            execution_id=(ADMISSION.get() or (None, uuid4().hex))[1],
            _decision_selections=decision_reuse or [],
        )
        with self.knowledge.store.transaction():
            self.knowledge.store.accept_job(job, request.strip())
            self.workspace._validate_reuse_sources(job["reused_decisions"])
        self.jobs[ident] = job
        ExecutionHistory(self.workspace.documents(ident)).start_execution(
            "generate", job["execution_id"], input_data=request.strip()
        )
        self._submit_locked(ident, "generate", request.strip())
        return copy.deepcopy(job)

    @synchronized
    def action(
        self, ident, action, payload, *, continuation=False, expected_execution_id=None
    ):
        self._require_open()
        if (
            sum(j.get("status") in {"queued", "running"} for j in self.jobs.values())
            >= 20
        ):
            raise CleanupConflict("작업 대기열이 가득 찼습니다.")
        job = self._get_locked(ident)
        if (
            expected_execution_id != job.get("execution_id")
            or action not in self.workspace.allowed(ident)
            or self._activities.get(ident)
        ):
            raise CleanupConflict("작업 상태가 바뀌었습니다. 최신 대화를 확인하세요.")
        previous = copy.deepcopy(job)
        if action == "retry":
            from backend.infrastructure.workflow_store import retry_state
            recovery = retry_state(self.workspace.documents(ident))
            if recovery["retry_requires_replay"] and not (isinstance(payload, dict) and payload.get("replay_pending") is True):
                raise CleanupConflict("이전 호출의 완료 여부가 불확실합니다. 추가 비용 가능성을 확인하고 미완료 단계를 다시 실행하세요.")
        self._next_order += 1
        now = _utc_now()
        job.update(
            status="queued",
            action=action,
            message="작업 대기 중",
            queued_at=now,
            updated_at=now,
            queue_order=self._next_order,
            execution_id=(ADMISSION.get() or (None, uuid4().hex))[1],
        )
        try:
            self.knowledge.store.record_action(job, payload)
            ExecutionHistory(self.workspace.documents(ident)).start_execution(
                action, job["execution_id"], input_data=payload
            )
            self._submit_locked(ident, action, payload)
        except Exception:
            self.jobs[ident] = previous
            raise
        return copy.deepcopy(job)

    def retry(self, ident, execution_id, *, replay_pending=False):
        return self.action(
            ident,
            "retry",
            {"retry_of": execution_id, "replay_pending": replay_pending},
            expected_execution_id=execution_id,
        )

    def continue_session(self, ident, payload, expected_execution_id):
        return self.action(
            ident, "continue", payload, expected_execution_id=expected_execution_id
        )

    @tracked
    def _run(self, ident, action, payload, *, meter=None):
        with self.lock:
            job = self._get_locked(ident)
            job.update(status="running", updated_at=_utc_now())
            if not self._save_locked(job, meter=meter):
                raise RuntimeError("작업 시작을 저장하지 못했습니다.")
        self._notify(job)
        history = ExecutionHistory(self.workspace.documents(ident))
        try:
            engine = self.workspace.engine(ident, meter=meter)
            result = engine.execute(
                action,
                job["request"] if action == "generate" else payload,
                on_progress=lambda event: self._engine_progress(
                    ident, event, meter=meter
                ),
            )
            status = result.status
            message = result.wait_reason if status == "CRITICAL_BLOCKED" and result.wait_reason else _message_for_status(status)
            diagnostic = None
        except Exception as exc:
            status, message, diagnostic = (
                "error",
                safe_user_error(exc),
                diagnose_exception(exc),
            )
            LOGGER.error(
                "job failed id=%s action=%s exception_type=%s",
                ident,
                action,
                type(exc).__name__,
            )
        with self.lock:
            job.update(status=status, message=message, updated_at=_utc_now())
            if diagnostic:
                self._set_error_metadata(job, diagnostic)
            else:
                self._clear_error_metadata(job)
            if not self._save_locked(job, meter=meter):
                raise RuntimeError("작업 결과를 저장하지 못했습니다.")
        state = self.workspace.state(ident)
        if action == "approve" and status == "FINALIZED":
            history.capture(job["execution_id"], "approve", state=state)
        history.terminal(job["execution_id"], status, message, result=state)
        self._notify(job)

    def _engine_progress(self, ident, event, *, meter=None):
        with self.lock:
            job = self._get_locked(ident)
            job["progress"] = {
                k: event[k] for k in ("stage", "state", "result") if k in event
            }
            job["updated_at"] = _utc_now()
            self.knowledge.store.save_job(
                job, expected_generation=meter.generation if meter else None
            )
        history = ExecutionHistory(self.workspace.documents(ident))
        history.stage(
            job["execution_id"],
            event["stage"],
            event["state"],
            result=event.get("result"),
        )
        if event["state"] == "completed":
            history.capture(
                job["execution_id"], event["stage"], state=self.workspace.state(ident)
            )
        self._notify(job)

    def _save_locked(self, job, *, meter=None):
        try:
            self.knowledge.store.save_job(
                job, expected_generation=meter.generation if meter else None
            )
            return True
        except (RuntimeError, ValueError, TypeError):
            return False

    def _notify(self, job):
        if self.on_change:
            self.on_change(
                {
                    "event": "job.changed",
                    "job": {k: job[k] for k in ("id", "status", "updated_at")},
                    "_owner_id": job.get("owner_id"),
                }
            )

    def ids(self) -> list[str]:
        with self.lock:
            return [
                job["id"]
                for job in sorted(
                    self.jobs.values(),
                    key=lambda item: (item.get("updated_at", ""), item["order"]),
                    reverse=True,
                )
                if ACTOR.get() is None or job.get("owner_id") == ACTOR.get()["id"]
            ]

    def get(self, ident: str) -> dict:
        with self.lock:
            return self._snapshot(self._get_locked(ident))

    def _submit_locked(self, ident: str, action: str, payload: object) -> None:
        deferred = DEFERRED.get()
        if deferred is not None:
            deferred.append((ident, action, payload))
            return
        service = getattr(self, "public_service", None)
        execution = None
        if service:
            from backend.access.recovery import Execution

            execution = Execution.from_job(self.jobs[ident])
        try:
            from contextvars import copy_context

            run = service.worker if service else self._run
            kwargs = {"execution": execution} if service else {}
            future = self.executor.submit(
                copy_context().run, run, ident, action, payload, **kwargs
            )
        except RuntimeError as exc:
            if service:
                from backend.access.recovery import Failure

                service.recovery.record(Failure(execution, False, execution.initial))
            raise RuntimeError("작업 큐를 사용할 수 없습니다.") from exc
        self._futures[future] = (ident, execution)
        future.add_done_callback(self._worker_done)

    def _worker_done(self, future):
        with self.lock:
            tracked = self._futures.pop(future, None)
        if tracked is None:
            return
        ident, execution = tracked
        if future.cancelled():
            if execution is not None:
                from backend.access.recovery import Failure

                self.public_service.recovery.record(
                    Failure(execution, False, execution.initial)
                )
            return
        exc = future.exception()
        if exc is not None:
            LOGGER.error(
                "worker failed job_id=%s execution_id=%s generation=%s exception_type=%s",
                ident,
                execution.execution_id if execution else None,
                execution.generation if execution else None,
                type(exc).__name__,
            )

    @staticmethod
    def _set_error_metadata(job: dict, diagnostic: dict) -> None:
        code = diagnostic.get("error_code")
        stage = diagnostic.get("error_stage")
        if isinstance(code, str) and isinstance(stage, str):
            job["error_code"] = code
            job["error_stage"] = stage
        else:
            JobManager._clear_error_metadata(job)

    @staticmethod
    def _clear_error_metadata(job: dict) -> None:
        job.pop("error_code", None)
        job.pop("error_stage", None)

    def _get_locked(self, ident: str) -> dict:
        if (
            not isinstance(ident, str)
            or not _ID.fullmatch(ident)
            or ident not in self.jobs
        ):
            raise KeyError(ident)
        job = self.jobs[ident]
        if ACTOR.get() is not None and job.get("owner_id") != ACTOR.get()["id"]:
            raise KeyError(ident)
        return job

    def _require_open(self) -> None:
        if self.closed:
            raise RuntimeError("서버가 종료 중입니다.")

    @staticmethod
    def _snapshot(job: dict) -> dict:
        return copy.deepcopy(job)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _message_for_status(status: str) -> str:
    return {
        "NEEDS_USER_INPUT": "진행에 필요한 요구사항을 확인해주세요.",
        "PASS_PENDING_USER_APPROVAL": "검토를 통과했습니다. 내용을 확인한 뒤 승인하세요.",
        "CRITICAL_BLOCKED": "진행이 중단되었습니다. 저장된 결과를 확인하고 수정 의견이나 추가 실행을 선택해주세요.",
        "FINALIZED": "최종 명세가 준비되었습니다.",
        "APPROVED": "승인이 처리되었습니다.",
    }.get(status, "작업이 완료되었습니다.")
