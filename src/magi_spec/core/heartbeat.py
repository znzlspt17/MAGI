"""Run heartbeat persistence for externally monitored MAGI runs."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any

from magi_spec.core.artifacts import ArtifactWriter
from magi_spec.core.state import MagiState


HEARTBEAT_PATH = "state/heartbeat.json"
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 10.0


class RunHeartbeat:
    """Periodically records that a MAGI run is still alive."""

    def __init__(
        self,
        *,
        writer: ArtifactWriter,
        state: MagiState,
        interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        self.writer = writer
        self.state = state
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"magi-heartbeat-{state.run_id}",
            daemon=True,
        )
        self._sequence = 0

    def __enter__(self) -> "RunHeartbeat":
        self.start()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: Any) -> None:
        self.stop(exc=exc)

    def start(self) -> None:
        self.write(running=True, lifecycle="started")
        self._thread.start()

    def stop(self, *, final_status: str | None = None, exc: BaseException | None = None) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1)
        lifecycle = "failed" if exc is not None else "stopped"
        extra: dict[str, Any] = {}
        if exc is not None:
            extra["error"] = {"type": type(exc).__name__, "message": str(exc)}
        self.write(
            running=False,
            lifecycle=lifecycle,
            status=final_status or self.state.status,
            extra=extra,
        )

    def write(
        self,
        *,
        running: bool,
        lifecycle: str,
        status: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self._sequence += 1
        payload: dict[str, Any] = {
            "run_id": self.state.run_id,
            "running": running,
            "lifecycle": lifecycle,
            "status": status or self.state.status,
            "sequence": self._sequence,
            "last_heartbeat_at": _utc_now_iso(),
            "interval_seconds": self.interval_seconds,
        }
        if extra:
            payload.update(extra)
        self.writer.write_json(HEARTBEAT_PATH, payload, overwrite=True)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.write(running=True, lifecycle="running")


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
