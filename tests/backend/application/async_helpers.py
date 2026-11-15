"""비동기 업무 테스트를 같은 이벤트 루프 안에서 실행한다."""

import asyncio
import inspect
import sys


def run_async(function):
    def run(*args, **kwargs):
        factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
        with asyncio.Runner(loop_factory=factory) as runner:
            return runner.run(function(*args, **kwargs))

    run.__name__ = function.__name__
    run.__doc__ = function.__doc__
    run.__signature__ = inspect.signature(function)
    return run
