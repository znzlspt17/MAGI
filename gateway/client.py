"""Synchronous client for the Flask gateway."""

from __future__ import annotations

import json
import os
from urllib.parse import urlsplit
from uuid import uuid4

from websockets.sync.client import connect

from protocol.messages import MAX_MESSAGE_BYTES
from protocol.errors import HTTP_STATUS, UNCERTAIN_METHODS, REJECTED_CODES


class ClientError(RuntimeError):
    """A safe, user-facing server connection or request error."""

    def __init__(self, message: str, *, status: int = 503, uncertain: bool = False, response_received: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.uncertain = uncertain
        self.response_received = response_received


class Client:
    def __init__(self, url: str) -> None:
        self.url = _loopback_url(url)
        self.context = {}
        self.internal_key = os.environ.get('INTERNAL_KEY','')

    def _headers(self):
        return {'X-Internal':self.internal_key} if self.internal_key else {}

    def call(self, method: str, params: dict | None = None) -> object:
        request_id = uuid4().hex
        request = {"request_id": request_id, "method": method, "params": params or {}}
        request.update(self.context)
        try:
            with connect(self.url, additional_headers=self._headers(), open_timeout=3, close_timeout=2, max_size=4 * 1024 * 1024) as socket:
                socket.send(json.dumps(request, ensure_ascii=False))
                raw = socket.recv(timeout=520 if method == "document" else 180 if method == "knowledge.impact.analyse" else 120 if method == "knowledge.search" or method.startswith('cleanup.') else 30 if method.startswith(("projects.", "knowledge.")) else 10)
        except Exception as exc:
            raise ClientError(
                "작업 서버에 연결할 수 없습니다. 서버 상태를 확인하세요.",
                uncertain=method in UNCERTAIN_METHODS,
            ) from exc
        try:
            response = _response(raw, request_id)
        except ClientError as exc:
            raise ClientError(
                str(exc),
                status=exc.status,
                uncertain=method in UNCERTAIN_METHODS,
            ) from exc
        if "error" in response:
            error = response["error"]
            if not isinstance(error, dict):
                raise ClientError("작업 서버 응답을 확인할 수 없습니다.")

            code = error.get("code")
            raise ClientError(
                error.get("message", "요청을 처리하지 못했습니다."),
                status=HTTP_STATUS.get(code, 503),
                response_received=True,
                uncertain=(
                    method in UNCERTAIN_METHODS
                    and code not in REJECTED_CODES
                ),
            )
        return response.get("result")

    def events(self):
        request_id = uuid4().hex
        request = {"request_id": request_id, "method": "subscribe", "params": {}}
        request.update(self.context)
        try:
            with connect(self.url, additional_headers=self._headers(), open_timeout=3, close_timeout=2, max_size=MAX_MESSAGE_BYTES) as socket:
                socket.send(json.dumps(request, ensure_ascii=False))
                response = _response(socket.recv(timeout=5), request_id)
                if "error" in response:
                    error = response["error"]
                    message = error.get("message") if isinstance(error, dict) else None
                    raise ClientError(message or "구독을 시작할 수 없습니다.")
                yield {"event": "ready"}
                while True:
                    try:
                        raw = socket.recv(timeout=5)
                    except TimeoutError:
                        yield {"event": "keepalive"}
                        continue
                    event = _event(raw)
                    if event is not None:
                        yield event
        except ClientError:
            raise
        except Exception as exc:
            raise ClientError("작업 서버 연결이 끊어졌습니다.") from exc


def _loopback_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"ws", "wss"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ClientError("작업 서버 주소가 올바르지 않습니다.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ClientError("작업 서버 주소가 올바르지 않습니다.")
    return url


def _response(raw: object, request_id: str) -> dict:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 4 * 1024 * 1024:
        raise ClientError("작업 서버 응답을 확인할 수 없습니다.")
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ClientError("작업 서버 응답을 확인할 수 없습니다.") from exc
    if not isinstance(response, dict) or response.get("request_id") != request_id:
        raise ClientError("작업 서버 응답을 확인할 수 없습니다.")
    return response


def _event(raw: object) -> dict | None:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 128 * 1024:
        return None
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return event if isinstance(event, dict) and isinstance(event.get("event"), str) else None
