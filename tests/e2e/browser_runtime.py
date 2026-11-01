"""실제 게이트웨이와 설치된 Playwright를 사용하는 브라우저 검증 도우미."""

from contextlib import contextmanager
from pathlib import Path
import os
import shutil
import subprocess
import threading

import pytest
from werkzeug.serving import make_server


def playwright_runtime():
    node = shutil.which("node")
    packages = (
        Path(os.environ["TEST_NODE_MODULES"])
        if os.environ.get("TEST_NODE_MODULES")
        else Path(__file__).resolve().parents[2] / "frontend/node_modules"
    )
    if not (packages / "playwright").is_dir():
        pytest.skip("Playwright Node 런타임이 없습니다.")
    return node, packages


@contextmanager
def gateway_server(app):
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def run_browser(script, base_url, *arguments, timeout=90):
    node, packages = playwright_runtime()
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            node,
            str(Path(__file__).with_name(script)),
            str(packages),
            base_url,
            *map(str, arguments),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout
