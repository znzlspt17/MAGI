"""Run the MAGI loopback WebSocket job server."""

from __future__ import annotations

import asyncio
import base64
import json
from protocol.logging import get_logger
import os
import hmac
import signal
from ipaddress import ip_address
from pathlib import Path

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from backend.errors import TranslationValidationError, InvalidStateError
from backend.server.diagnostics import diagnose_exception, safe_user_error
from backend.server.job_manager import JobManager
from backend.server.cleanup import CleanupConflict
from protocol.messages import (
    MAX_MESSAGE_BYTES,
    error,
    parse_request,
    result as rpc_result,
)


LOGGER = get_logger("backend.server")
_ADDRESS = "ws://127.0.0.1:8765"


def configure_logging() -> None:
    from protocol.logging import configure_logging as configure
    configure("backend")


class Server:
    def __init__(self, knowledge, *, public=None, internal_key="") -> None:
        self.loop = asyncio.get_running_loop()
        self.subscribers: set[asyncio.Queue[str]] = set()
        self.manager = JobManager(knowledge, on_change=self.publish_from_worker)
        self.public = public(self.manager) if public is not None else None
        self.internal_key = internal_key
        self.subscriber_owners = {}

    def publish_from_worker(self, event: dict) -> None:
        try:
            self.loop.call_soon_threadsafe(self._publish, event)
        except RuntimeError:
            return

    def _publish(self, event: dict) -> None:
        message = json.dumps(
            {key: value for key, value in event.items() if key != "_owner_id"},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for queue in tuple(self.subscribers):
            if self.public:
                uid = self.subscriber_owners.get(queue)
                jid = event.get("job", {}).get("id")
                owner = event.get("_owner_id") or self.manager.jobs.get(jid, {}).get(
                    "owner_id"
                )
                if owner != uid:
                    continue
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(message)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    continue

    async def handler(self, socket) -> None:
        queue: asyncio.Queue[str] | None = None
        sender: asyncio.Task | None = None
        if self.public or self.internal_key:
            # 공개 경로는 게이트웨이뿐이다. 브라우저와 비로컬 RPC 연결은 받지 않는다.
            peer = socket.remote_address
            if (
                not peer
                or not ip_address(peer[0]).is_loopback
                or (socket.request and "Origin" in socket.request.headers)
            ):
                await socket.close(code=1008)
                return
            supplied = (
                socket.request.headers.get("X-Internal", "") if socket.request else ""
            )
            if self.internal_key and not hmac.compare_digest(
                supplied, self.internal_key
            ):
                await socket.close(code=1008)
                return
        try:
            async for raw in socket:
                request = parse_request(raw)
                if request is None:
                    await socket.send(
                        error("", "요청 형식이 올바르지 않습니다.", "invalid")
                    )
                    continue
                request_id = request["request_id"]
                if request["method"] == "subscribe":
                    if self.public:
                        try:
                            actor = await asyncio.to_thread(
                                self.public.access.session, request.get("session")
                            )
                        except Exception:
                            await socket.send(
                                error(
                                    request_id, "로그인이 필요합니다.", "unauthorized"
                                )
                            )
                            return
                    if queue is None:
                        queue = asyncio.Queue(maxsize=32)
                        self.subscribers.add(queue)
                        if self.public:
                            self.subscriber_owners[queue] = actor["id"]
                    await socket.send(rpc_result(request_id, {"ready": True}))
                    if sender is None:
                        sender = asyncio.create_task(
                            self._sender(socket, queue, request.get("session"))
                        )
                    continue
                response = await asyncio.to_thread(self._dispatch, request)
                await socket.send(response)
        except ConnectionClosed:
            return
        except Exception as exc:
            _log_exception("websocket handler failed", exc)
            return
        finally:
            if queue is not None:
                self.subscribers.discard(queue)
                self.subscriber_owners.pop(queue, None)
            if sender is not None:
                sender.cancel()

    async def _sender(self, socket, queue: asyncio.Queue[str], sid=None) -> None:
        while True:
            try:
                if self.public:
                    try:
                        message = await asyncio.wait_for(queue.get(), timeout=5)
                    except asyncio.TimeoutError:
                        actor = await asyncio.to_thread(self.public.access.session, sid)
                        status = await asyncio.to_thread(
                            self.public.access.status, actor["id"]
                        )
                        message = json.dumps(
                            {"event": "service.status", "status": status}
                        )
                    else:
                        # 진행 이벤트를 전송하기 직전에 세션 철회 여부를 확인한다.
                        await asyncio.to_thread(self.public.access.session, sid)
                    await socket.send(message)
                else:
                    await socket.send(await queue.get())
            except ConnectionClosed:
                return
            except Exception as exc:
                if self.public:
                    await socket.close(code=1008)
                    return
                _log_exception("websocket sender failed", exc)
                return

    def _dispatch(self, request: dict) -> str:
        from protocol.logging import log_context
        from time import monotonic
        with log_context(trace_id=request.get("trace_id"), request_id=request["request_id"]):
            started = monotonic()
            try:
                return self._dispatch_logged(request)
            finally:
                LOGGER.info("rpc_completed", method=request["method"],
                            duration_ms=round((monotonic() - started) * 1000, 2))

    def _dispatch_logged(self, request: dict) -> str:
        if request["method"] == "health.check":
            # 내부 키를 검사한 loopback 소켓에서만 DB 준비 상태를 확인한다.
            if (
                not self.internal_key
                or self.manager.closed
                or self.manager.knowledge is None
            ):
                return error(
                    request["request_id"], "준비되지 않았습니다.", "unavailable"
                )
            try:
                store = self.manager.knowledge.store
                with store.connect(**store.config.connection) as connection:
                    connection.execute("SET LOCAL statement_timeout = '3s'")
                    connection.execute("SELECT 1").fetchone()
                return rpc_result(request["request_id"], {"ready": True})
            except Exception:
                return error(
                    request["request_id"], "준비되지 않았습니다.", "unavailable"
                )
        if self.public:
            from backend.access.context import AccessError

            try:
                return rpc_result(
                    request["request_id"],
                    self.public.invoke(request, self._dispatch_request),
                )
            except AccessError as exc:
                LOGGER.warning(
                    "public request rejected method=%s category=%s request_id=%s",
                    request["method"],
                    exc.code,
                    request["request_id"],
                )
                return error(request["request_id"], str(exc), exc.code)
            except KeyError:
                LOGGER.warning(
                    "public request rejected method=%s category=not_found request_id=%s",
                    request["method"],
                    request["request_id"],
                )
                return error(
                    request["request_id"], "작업을 찾을 수 없습니다.", "not_found"
                )
            except Exception as exc:
                _log_exception("public dispatch failed", exc, method=request["method"])
                return error(
                    request["request_id"], "요청을 처리하지 못했습니다.", "unavailable"
                )
        if request["method"].startswith(("admin.", "cleanup.")):
            return error(
                request["request_id"],
                "관리자 인증이 설정된 서비스에서만 사용할 수 있습니다.",
                "forbidden",
            )
        return error(
            request["request_id"], "인증 서비스가 필요합니다.", "configuration"
        )

    def _dispatch_request(self, request: dict):
        from backend.access.context import AccessError
        from protocol.commands import COMMAND_KINDS
        from protocol.messages import RPC_METHODS

        method, params = request["method"], request["params"]
        try:
            if method in COMMAND_KINDS:
                if method == "generate":
                    job = self.manager.create(
                        params.get("request"),
                        project_id=params.get("project_id"),
                        decision_reuse=params.get("decision_reuse"),
                    )
                else:
                    payload = (
                        {"retry_of": params["execution_id"], "replay_pending": params.get("replay_pending", False)}
                        if method == "retry"
                        else {"candidate_hash": params["candidate_hash"]}
                        if method == "approve"
                        else params.get("payload")
                    )
                    job = self.manager.action(
                        _ident(params),
                        method,
                        payload,
                        expected_execution_id=params.get("execution_id"),
                    )
                return self.manager.workspace.summary(job["id"])
            handler = RPC_METHODS.get(method)
            if handler is None:
                raise AccessError("지원하지 않는 요청입니다.", "invalid")
            return getattr(self, handler)(params, request)
        except (InvalidStateError, CleanupConflict) as exc:
            raise AccessError(safe_user_error(exc), "conflict") from None
        except TranslationValidationError as exc:
            _log_exception("dispatch failed", exc, method=method)
            raise AccessError(
                diagnose_exception(exc)["reason"], "translation_invalid"
            ) from None
        except ValueError:
            raise AccessError(
                "입력 또는 현재 작업 상태를 확인하세요.", "invalid"
            ) from None

    def _list_jobs(self, params, request):
        return [self.manager.workspace.summary(ident) for ident in self.manager.ids()]

    def _get_job(self, params, request):
        ident = _ident(params)
        return (
            self.manager.workspace.step(ident, params["step_id"])
            if "step_id" in params
            else self.manager.workspace.public(ident)
        )

    def _document(self, params, request):
        return self.manager.workspace.document(
            _ident(params),
            params.get("step_id"),
            params.get("language"),
            meter=request.get("_meter"),
        )

    def _download(self, params, request):
        ident = _ident(params)
        if self.manager.get(ident)["status"] != "FINALIZED":
            raise KeyError(ident)
        content = self.manager.workspace.documents(ident).read_text(
            "final/FINAL_AGENT_SPEC.md"
        )
        return {
            "name": "FINAL_AGENT_SPEC.md",
            "content": base64.b64encode(content.encode()).decode("ascii"),
        }

    def _requirement_review(self, params, request):
        return self.manager.workspace.requirement_review(_ident(params), params)

    def _implementation_package(self, params, request):
        return self.manager.workspace.implementation_package(
            _ident(params), params, read_file=request["method"].endswith(".file")
        )

    def _knowledge(self, params, request):
        return self.manager.workspace.knowledge_call(request["method"], params)

    def _impact(self, params, request):
        return self.manager.workspace.impact(params)

    def _impact_analyse(self, params, request):
        return self.manager.workspace.impact_analyse(
            params.get("job_id"),
            params,
            request.get("idempotency_key"),
            meter=request.get("_meter"),
        )


def _ident(params: dict) -> str:
    ident = params.get("id")
    if not isinstance(ident, str):
        raise KeyError(ident)
    return ident


async def main() -> None:
    configure_logging()
    from backend.knowledge.config import KnowledgeConfig
    from backend.knowledge.runtime import KnowledgeService
    from backend.knowledge.store import KnowledgeStore
    from protocol.deployment import validate_container

    validate_container("backend")
    if os.environ.get("CONTAINER") == "1":
        from backend.knowledge.model_files import verify_prepared_model

        verify_prepared_model(os.environ["EMBEDDING_MODEL_PATH"])
    internal_key = os.environ.get("INTERNAL_KEY", "")
    runtime = None
    try:
        config = KnowledgeConfig.from_env()
        store = KnowledgeStore(config)
        from backend.access.runtime import PublicRuntime, service_factory
        from backend.knowledge.setup import migrate

        runtime = PublicRuntime(store)
        runtime.acquire(recover=False)
        migrate(store, runtime=runtime)
        runtime.recover()
        knowledge = KnowledgeService(store)
        server = Server(knowledge, public=service_factory, internal_key=internal_key)
    except Exception as exc:
        _log_exception("server initialization failed", exc)
        if runtime:
            runtime.close()
        raise SystemExit(1) from None
    loop = asyncio.get_running_loop()
    stopped = asyncio.Event()
    registered_signals = []
    # Linux 컨테이너의 SIGTERM을 정상 종료 경로로 연결한다.
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, stopped.set)
            registered_signals.append(signum)
        except (NotImplementedError, RuntimeError):
            pass
    try:
        async with serve(
            server.handler,
            "127.0.0.1",
            8765,
            origins=[None],
            max_size=MAX_MESSAGE_BYTES,
            max_queue=16,
        ):
            LOGGER.info("server started address=%s", _ADDRESS)
            await stopped.wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        LOGGER.info("server shutdown requested address=%s", _ADDRESS)
    except Exception as exc:
        _log_exception("server stopped unexpectedly", exc)
        raise SystemExit(1) from None
    finally:
        for signum in registered_signals:
            loop.remove_signal_handler(signum)
        await asyncio.to_thread(server.manager.close)
        if runtime:
            runtime.close()
        LOGGER.info("server stopped address=%s", _ADDRESS)


def _log_exception(
    event: str, exc: BaseException, *, method: str | None = None
) -> None:
    diagnostic = diagnose_exception(exc)
    LOGGER.error(
        event, method=method, error_code=diagnostic["error_code"],
        error_stage=diagnostic["error_stage"], failed_checks=diagnostic["failed_checks"],
        exception_type=diagnostic["exception_type"], frames=diagnostic["frames"],
        validation_reason=diagnostic["validation_reason"], validation_section=diagnostic["validation_section"],
        validation_index=diagnostic["validation_index"], validation_field=diagnostic["validation_field"],
    )


if __name__ == "__main__":
    asyncio.run(main())
