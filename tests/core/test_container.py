"""서비스 실패 시 재실행하지 않고 대기하며 중지 신호를 전달한다."""

import signal

import pytest

from protocol import container


@pytest.mark.parametrize("exit_code", [0, 1])
def test_service_exit_waits_without_retry(monkeypatch, caplog, exit_code):
    calls = []
    handlers = {}

    class Child:
        def wait(self):
            return exit_code

    class Event:
        stopped = False

        def is_set(self):
            return self.stopped

        def set(self):
            self.stopped = True

        def wait(self):
            calls.append("idle")
            handlers[signal.SIGTERM](signal.SIGTERM, None)

    def start(args):
        calls.append(args)
        return Child()

    monkeypatch.setattr(container.sys, "argv", ["runner", "python", "-m", "backend.server"])
    monkeypatch.setattr(container.subprocess, "Popen", start)
    monkeypatch.setattr(container.threading, "Event", Event)
    monkeypatch.setattr(container.signal, "signal", lambda sig, fn: handlers.update({sig: fn}))
    monkeypatch.setattr(Child, "poll", lambda self: exit_code, raising=False)
    container.main()
    assert calls == [["python", "-m", "backend.server"], "idle"]
    assert "exit_code=" + str(exit_code) in caplog.text


def test_stop_forwards_signal_and_exits_without_idle(monkeypatch):
    handlers = {}
    sent = []

    class Child:
        def poll(self):
            return None

        def send_signal(self, sig):
            sent.append(sig)

        def wait(self):
            handlers[signal.SIGTERM](signal.SIGTERM, None)
            return -signal.SIGTERM

    monkeypatch.setattr(container.sys, "argv", ["runner", "python"])
    monkeypatch.setattr(container.subprocess, "Popen", lambda args: Child())
    monkeypatch.setattr(container.signal, "signal", lambda sig, fn: handlers.update({sig: fn}))
    container.main()
    assert sent == [signal.SIGTERM]
