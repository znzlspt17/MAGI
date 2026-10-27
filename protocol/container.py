"""서비스 종료 후 컨테이너를 유지해 운영자가 오류를 점검할 수 있게 한다."""

from protocol.logging import get_logger
import signal
import subprocess
import sys
import threading


def main():
    from protocol.logging import configure_logging
    configure_logging("backend")
    stopped = threading.Event()
    child = None

    def stop(signum, _frame):
        stopped.set()
        if child is not None and child.poll() is None:
            child.send_signal(signum)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        child = subprocess.Popen(sys.argv[1:])
        # 프로세스 생성 도중 도착한 종료 요청도 전달한다.
        if stopped.is_set() and child.poll() is None:
            child.terminate()
        code = child.wait()
    except OSError:
        # 실행 인자나 OS 오류 원문에는 보호된 정보가 포함될 수 있다.
        get_logger(__name__).error("서비스 프로세스를 시작하지 못했습니다.")
    else:
        if not stopped.is_set():
            get_logger(__name__).error("서비스 프로세스가 종료되었습니다. exit_code=%s", code)
    if not stopped.is_set():
        get_logger(__name__).error("자동 재시도 없이 컨테이너를 유지합니다. 원인 해결 후 컨테이너를 재시작하세요.")
        stopped.wait()


if __name__ == "__main__":
    main()
