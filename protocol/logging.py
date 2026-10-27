"""컨테이너용 JSON 로그와 요청별 안전한 진단 문맥."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
import logging
import re
import sys

import orjson
import structlog

TRACE_ID = ContextVar("log_trace_id", default=None)
_SERVICE = "backend"
_GENERATION = 0
_FIELDS = {"trace_id", "request_id", "job_id", "execution_id", "stage", "duration_ms",
           "error_code", "error_stage", "exception_type", "frames", "failed_checks",
           "attempt", "max_attempts", "method", "status", "logger_name"}
_SENSITIVE = re.compile(
    r"(?i)(authorization|cookie|set-cookie)\s*[:=]\s*[^\r\n]+|"
    r"\b(?:sk-[a-zA-Z0-9_-]{8,})\b|"
    r"(?:postgres(?:ql)?|https?)://[^\s/@:]+:[^\s/@]+@[^\s]+|"
    r'\b(?:password|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|'
    r'internal[_-]?key|subject[_-]?pepper|code|state)"?\s*[:=]\s*"?[^\s,;&"]+'
)


class _Stderr:
    def write(self, value):
        return sys.stderr.write(value)

    def flush(self):
        return sys.stderr.flush()


class _StderrBytes:
    def write(self, value):
        if hasattr(sys.stderr, "buffer"):
            return sys.stderr.buffer.write(value)
        return sys.stderr.write(value.decode())

    def flush(self):
        return sys.stderr.flush()


_STDERR, _STDERR_BYTES = _Stderr(), _StderrBytes()


def redact(value: str) -> str:
    return _SENSITIVE.sub("[REDACTED]", value)[:16384]


def _safe(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value[:100]]
    if isinstance(value, dict):
        return {str(key): "[REDACTED]" if re.search(r"(?i)password|secret|token|api.?key|cookie|authorization", str(key)) else _safe(item)
                for key, item in list(value.items())[:100]}
    if isinstance(value, (int, float, bool, type(None))):
        return value
    return type(value).__name__


def _render(_, method, event):
    message = redact(str(event.get("event", "")))
    result = {key: value for key, value in event.items() if key in _FIELDS}
    # 예외 본문과 지역변수를 serializer에 전달하지 않는다.
    exc = event.get("exc_info")
    if exc:
        item = exc if isinstance(exc, BaseException) else sys.exc_info()[1]
        result["exception_type"] = type(item).__name__ if item else "Exception"
    result = {key: _safe(value) for key, value in result.items()}
    result.update(timestamp=datetime.now(UTC).isoformat(), service=_SERVICE,
                  level="warning" if method == "warn" else method,
                  event=message.split(" ", 1)[0] or "log", message=message)
    return result


class _JSONFormatter(logging.Formatter):
    def format(self, record):
        # 외부 라이브러리 traceback은 예외 종류만 남긴다.
        own = record.name.startswith(("backend.", "gateway.", "protocol."))
        event = {"event": record.getMessage() if own else "library_log", "logger_name": record.name}
        event.update(structlog.contextvars.get_contextvars())
        if record.exc_info:
            event["exception_type"] = record.exc_info[0].__name__
        return orjson.dumps(_render(None, record.levelname.lower(), event)).decode()


def configure_logging(service: str, *, stream=None) -> None:
    global _SERVICE, _GENERATION
    _SERVICE = service
    _GENERATION += 1
    target = stream if stream is not None else _STDERR
    # 캡처 스트림도 지원하며 서비스 시작 전에 한 번 설정한다.
    binary = stream is None or hasattr(target, "buffer")
    factory = (structlog.BytesLoggerFactory(file=_STDERR_BYTES if stream is None else target.buffer)
               if binary else structlog.WriteLoggerFactory(file=target))
    serializer = orjson.dumps if binary else lambda v, **kw: orjson.dumps(v, **kw).decode()
    structlog.configure(
        cache_logger_on_first_use=True,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=factory,
        processors=[structlog.contextvars.merge_contextvars, _render,
                    structlog.processors.JSONRenderer(serializer=serializer)],
    )
    for name in ("", "backend.server", "gateway.app", "flask.app", "gunicorn.error", "gunicorn.access"):
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            if getattr(handler, "_magi_json", False) or getattr(handler, "_server", False):
                logger.removeHandler(handler)
        if name:
            logger.handlers.clear()
            logger.propagate = True
            continue
        handler = logging.StreamHandler(target)
        handler._magi_json = True
        handler.setFormatter(_JSONFormatter())
        logger.addHandler(handler)
    # 외부 SDK의 로그 레벨은 변경하지 않는다.


class _Logger:
    """초기화·테스트 스트림 교체 시 이전 출력 핸들을 재사용하지 않는다."""
    def __init__(self, name):
        self.name, self.generation, self.native = name, -1, None

    def _get(self):
        if self.generation != _GENERATION:
            self.native = structlog.get_logger(logger_name=self.name).bind()
            self.generation = _GENERATION
        return self.native

    def debug(self, event, *args, **fields):
        return self._get().debug(event, *args, **fields)

    def info(self, event, *args, **fields):
        return self._get().info(event, *args, **fields)

    def warning(self, event, *args, **fields):
        return self._get().warning(event, *args, **fields)

    def error(self, event, *args, **fields):
        return self._get().error(event, *args, **fields)

    def exception(self, event, *args, **fields):
        return self._get().exception(event, *args, **fields)


def get_logger(name: str):
    return _Logger(name)


@contextmanager
def log_context(**values):
    token = TRACE_ID.set(values.get("trace_id", TRACE_ID.get()))
    bound = structlog.contextvars.bind_contextvars(**{k: v for k, v in values.items() if v is not None})
    try:
        yield
    finally:
        structlog.contextvars.reset_contextvars(**bound)
        TRACE_ID.reset(token)
