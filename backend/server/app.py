"""Run the MAGI loopback WebSocket job server."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import hmac
import signal
from ipaddress import ip_address
from pathlib import Path

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from backend.errors import TranslationValidationError, ConversationUnavailableError, InvalidStateError
from backend.server.diagnostics import diagnose_exception
from backend.server.job_manager import JobManager
from backend.server.cleanup import CleanupConflict
from protocol.messages import (
    MAX_MESSAGE_BYTES,
    error,
    parse_request,
    result as rpc_result,
)


LOGGER = logging.getLogger("backend.server")
_ADDRESS = "ws://127.0.0.1:8765"


def configure_logging() -> None:
    """서버 로그만 표준 오류 출력에 남긴다.

    전역 로거 또는 SDK·HTTP 라이브러리의 로그 수준은 변경하지 않는다.
    """
    if not any(getattr(handler, "_server", False) for handler in LOGGER.handlers):
        handler = logging.StreamHandler()
        handler._server = True  # type: ignore[attr-defined]
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


class Server:
    def __init__(self, data_dir: str | Path, knowledge=None, *, public=None, internal_key='') -> None:
        self.loop = asyncio.get_running_loop()
        self.subscribers: set[asyncio.Queue[str]] = set()
        self.manager = JobManager(data_dir, on_change=self.publish_from_worker, knowledge=knowledge)
        self.public = public(self.manager) if public is not None else None
        self.internal_key = internal_key
        self.subscriber_owners = {}

    def publish_from_worker(self, event: dict) -> None:
        try:
            self.loop.call_soon_threadsafe(self._publish, event)
        except RuntimeError:
            return

    def _publish(self, event: dict) -> None:
        message = json.dumps({key:value for key,value in event.items() if key!='_owner_id'}, ensure_ascii=False, separators=(",", ":"))
        for queue in tuple(self.subscribers):
            if self.public:
                uid = self.subscriber_owners.get(queue)
                jid = event.get('job',{}).get('id')
                owner=event.get('_owner_id') or self.manager.jobs.get(jid,{}).get('owner_id')
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
            if not peer or not ip_address(peer[0]).is_loopback or (socket.request and 'Origin' in socket.request.headers):
                await socket.close(code=1008)
                return
            supplied = socket.request.headers.get('X-Internal','') if socket.request else ''
            if self.internal_key and not hmac.compare_digest(supplied,self.internal_key):
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
                            actor = await asyncio.to_thread(self.public.access.session, request.get('session'))
                        except Exception:
                            await socket.send(error(request_id,'로그인이 필요합니다.','unauthorized'))
                            return
                    if queue is None:
                        queue = asyncio.Queue(maxsize=32)
                        self.subscribers.add(queue)
                        if self.public:
                            self.subscriber_owners[queue]=actor['id']
                    await socket.send(rpc_result(request_id, {"ready": True}))
                    if sender is None:
                        sender = asyncio.create_task(self._sender(socket, queue, request.get('session')))
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
                self.subscriber_owners.pop(queue,None)
            if sender is not None:
                sender.cancel()

    async def _sender(self, socket, queue: asyncio.Queue[str], sid=None) -> None:
        while True:
            try:
                if self.public:
                    try:
                        message=await asyncio.wait_for(queue.get(),timeout=5)
                    except asyncio.TimeoutError:
                        actor=await asyncio.to_thread(self.public.access.session,sid)
                        status=await asyncio.to_thread(self.public.access.status,actor['id'])
                        message=json.dumps({'event':'service.status','status':status})
                    else:
                        # 진행 이벤트를 전송하기 직전에 세션 철회 여부를 확인한다.
                        await asyncio.to_thread(self.public.access.session,sid)
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
        if request['method'] == 'health.check':
            # 내부 키를 검사한 loopback 소켓에서만 DB 준비 상태를 확인한다.
            if not self.internal_key or self.manager.closed or self.manager.knowledge is None:
                return error(request['request_id'], '준비되지 않았습니다.', 'unavailable')
            try:
                store = self.manager.knowledge.store
                with store.connect(**store.config.connection) as connection:
                    connection.execute("SET LOCAL statement_timeout = '3s'")
                    connection.execute("SELECT 1").fetchone()
                return rpc_result(request['request_id'], {'ready': True})
            except Exception:
                return error(request['request_id'], '준비되지 않았습니다.', 'unavailable')
        if self.public:
            from backend.access.context import AccessError
            try:
                return rpc_result(request['request_id'],self.public.invoke(request,self._dispatch_legacy))
            except AccessError as exc:
                LOGGER.warning('public request rejected method=%s category=%s request_id=%s',request['method'],exc.code,request['request_id'])
                return error(request['request_id'],str(exc),exc.code)
            except KeyError:
                LOGGER.warning('public request rejected method=%s category=not_found request_id=%s',request['method'],request['request_id'])
                return error(request['request_id'],'작업을 찾을 수 없습니다.','not_found')
            except Exception as exc:
                _log_exception('public dispatch failed',exc,method=request['method'])
                return error(request['request_id'],'요청을 처리하지 못했습니다.','unavailable')
        if request['method'].startswith(('admin.','cleanup.')):
            return error(request['request_id'],'관리자 인증이 설정된 서비스에서만 사용할 수 있습니다.','forbidden')
        return self._dispatch_legacy(request)

    def _dispatch_legacy(self, request: dict) -> str:
        request_id = request["request_id"]
        method = request["method"]
        params = request["params"]
        try:
            if method == "list":
                payload = [self.manager.summary(ident) for ident in self.manager.ids()]
            elif method == "get":
                ident = _ident(params)
                step_id = params.get("step_id")
                payload = (
                    self.manager.step(ident, step_id)
                    if isinstance(step_id, str)
                    else self.manager.public(ident)
                )
            elif method == "requirement.review":
                payload = self.manager.requirement_review(_ident(params), params)
            elif method == "document":
                step_id = params.get("step_id")
                language = params.get("language")
                if not isinstance(step_id, str) or not isinstance(language, str) or language not in {"ko", "en"}:
                    raise ValueError("Invalid document request")
                payload = self.manager.document(_ident(params), step_id, language)
            elif method == "generate":
                payload = self.manager.summary(
                    self.manager.create(
                        params.get("request"),
                        params.get("demo"),
                        params.get("provider"),
                        params.get("project_id"),
                    )["id"]
                )
            elif method.startswith("cleanup."):
                action = method.split(".")[1]
                payload = (self.manager.cleanup.catalog() if action == "catalog" else
                           getattr(self.manager.cleanup, action)(params))
                if action == "execute":
                    self.publish_from_worker({"event": "records.deleted", "ids": payload["targets"]})
            elif method == "knowledge.impact":
                payload = self.manager.impact(params)
            elif method == "knowledge.impact.analyse":
                from backend.knowledge.projection import digest
                payload = self.manager.impact_analyse(params.get("job_id"), params, request.get("idempotency_key") or digest(params))
            elif method.startswith(("projects.", "knowledge.")):
                payload = self.manager.knowledge_call(method, params)
            elif method == "continue":
                job = self.manager.continue_session(_ident(params), params.get("payload"), params.get("execution_id"))
                payload = self.manager.summary(job["id"])
            elif method in {"answer", "revise", "approve"}:
                job = self.manager.action(_ident(params), method, params.get("payload"))
                payload = self.manager.summary(job["id"])
            elif method == "download":
                ident = _ident(params)
                if self.manager.get(ident).get("status") != "FINALIZED":
                    raise KeyError(ident)
                path = self.manager.artifact(ident, "final/FINAL_AGENT_SPEC.md")
                payload = {
                    "name": "FINAL_AGENT_SPEC.md",
                    "content": base64.b64encode(path.read_bytes()).decode("ascii"),
                }
            else:
                return error(request_id, "요청을 처리할 수 없습니다.", "invalid")
        except (ConversationUnavailableError, InvalidStateError) as exc:
            from backend.server.diagnostics import safe_user_error
            return error(request_id, safe_user_error(exc), "conflict")
        except CleanupConflict as exc:
            return error(request_id, str(exc), "conflict")
        except TranslationValidationError as exc:
            _log_exception("dispatch failed", exc, method=method)
            return error(request_id, diagnose_exception(exc)["reason"], "translation_invalid")
        except KeyError:
            LOGGER.info("dispatch rejected method=%s category=not_found", method)
            return error(request_id, "작업을 찾을 수 없습니다.", "not_found")
        except ValueError:
            LOGGER.info("dispatch rejected method=%s category=invalid", method)
            return error(
                request_id, "입력 또는 현재 작업 상태를 확인하세요.", "invalid"
            )
        except RuntimeError:
            LOGGER.info("dispatch rejected method=%s category=conflict", method)
            return error(request_id, "작업 서버를 사용할 수 없습니다.", "conflict")
        except Exception as exc:
            _log_exception("dispatch failed", exc, method=method)
            return error(request_id, "요청을 처리하지 못했습니다.", "internal")
        return rpc_result(request_id, payload)


def _ident(params: dict) -> str:
    ident = params.get("id")
    if not isinstance(ident, str):
        raise KeyError(ident)
    return ident


async def main() -> None:
    configure_logging()
    from backend.knowledge.config import KnowledgeConfig, load_environment
    from backend.knowledge.runtime import KnowledgeService
    from backend.knowledge.store import KnowledgeStore
    load_environment()
    from protocol.deployment import validate_container
    validate_container('backend')
    if os.environ.get('CONTAINER') == '1':
        from backend.knowledge.prepare_model import verify_prepared_model
        verify_prepared_model(os.environ['EMBEDDING_MODEL_PATH'])
    public_mode=os.environ.get('PUBLIC_MODE','1')!='0'
    internal_key=os.environ.get('INTERNAL_KEY','')
    runtime=None
    data_dir = os.environ.get("DATA_DIR", str(Path.cwd() / "web_data"))
    try:
        from backend.knowledge.format_guard import require_current
        require_current(data_dir)
        config = KnowledgeConfig.from_env()
        knowledge = None
        if config is not None:
            store = KnowledgeStore(config)
            store.migrate()
            knowledge = KnowledgeService(store)
        if public_mode:
            if knowledge is None:
                raise InvalidStateError('공개 모드에는 PostgreSQL 설정이 필요합니다.')
            from backend.access.runtime import PublicRuntime,service_factory
            runtime=PublicRuntime(store)
            runtime.acquire()
        server = Server(data_dir, knowledge=knowledge,public=service_factory if public_mode else None,internal_key=internal_key)
        if knowledge is not None and not public_mode:
            knowledge.schedule()
    except Exception as exc:
        _log_exception("server initialization failed", exc)
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
    method_part = f" method={method}" if method is not None else ""
    LOGGER.error(
        "%s%s reason=%s error_code=%s error_stage=%s failed_checks=%s exception_type=%s cause_types=%s http_status=%s frames=%s",
        event,
        method_part,
        diagnostic["reason"],
        diagnostic["error_code"],
        diagnostic["error_stage"],
        diagnostic["failed_checks"],
        diagnostic["exception_type"],
        diagnostic["cause_types"],
        diagnostic["http_status"],
        diagnostic["frames"],
    )


if __name__ == "__main__":
    asyncio.run(main())
