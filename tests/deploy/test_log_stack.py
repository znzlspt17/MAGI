"""명시적으로 켠 전용 Docker fixture에서 수집·재생성·전송 복구를 확인한다."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.parse import urlencode
from urllib.request import urlopen
from uuid import uuid4

import pytest
import yaml


@pytest.mark.skipif(os.environ.get("MAGI_RUN_LOG_STACK_TESTS") != "1" or not shutil.which("docker"), reason="전용 Docker 시험은 MAGI_RUN_LOG_STACK_TESTS=1과 Docker가 필요합니다.")
def test_log_stack_persistence_and_recovery(tmp_path):
    root = Path(__file__).resolve().parents[2]
    project = "magi-log-test-" + uuid4().hex[:10]
    config = yaml.safe_load((root / "deploy/compose.logs.yaml").read_text(encoding="utf-8"))
    vector = yaml.safe_load((root / "deploy/vector.yaml").read_text(encoding="utf-8"))
    postgres = project + "-postgres"
    app = project + "-app"
    for folder in ("storage", "buffer"):
        path = tmp_path / folder; path.mkdir(); path.chmod(0o777)
    vector["sources"]["apps"] = {"type": "docker_logs", "include_containers": [app]}
    vector["sources"]["postgres"]["include_containers"] = [postgres]
    (tmp_path / "vector.yaml").write_text(yaml.safe_dump(vector, allow_unicode=True), encoding="utf-8")
    config["name"] = project
    config["networks"]["logs"]["name"] = project
    for name, service in config["services"].items():
        service.pop("platform", None)
        for volume in service["volumes"]:
            if isinstance(volume, dict):
                volume["source"] = str(tmp_path / ({"/storage": "storage", "/var/lib/vector": "buffer", "/etc/vector/vector.yaml": "vector.yaml"}[volume["target"]]))
    config["services"]["vector"]["environment"]["MAGI_POSTGRES_CONTAINER"] = postgres
    config["services"]["victorialogs"]["ports"] = ["127.0.0.1:0:9428"]
    fixture = {"image": "busybox:1.37.0", "networks": ["logs"], "logging": {"driver": "local", "options": {"max-size": "20k", "max-file": "3"}}}
    config["services"]["app"] = {**fixture, "container_name": app, "labels": {"dev.magi.logs": "true", "dev.magi.service": "backend"},
                                     "command": ["sh", "-c", 'while :; do echo \'{"level":"info","message":"fixture-event","validation_reason":"duplicate_item_id","validation_section":"background","validation_index":0,"validation_field":"item_id"}\'; sleep 1; done']}
    config["services"]["postgres"] = {**fixture, "container_name": postgres, "command": ["sh", "-c", "while :; do echo 'LOG: database system is ready to accept connections'; sleep 1; done"]}
    compose = tmp_path / "compose.yaml"
    compose.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    # Compose의 자동 .env 탐색 대신 비밀값 없는 전용 입력을 사용한다.
    envfile = tmp_path / "fixture.vars"; envfile.write_text("", encoding="utf-8")
    base = ["docker", "compose", "--env-file", str(envfile), "-p", project, "-f", str(compose)]
    def run(*args):
        result = subprocess.run([*base, *args], capture_output=True, text=True, timeout=180)
        assert result.returncode == 0, f"Docker fixture command failed: {args[0]}"
        return result.stdout.strip()
    def eventually(check):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                value = check()
                if value: return value
            except (OSError, ValueError): pass
            time.sleep(.5)
        pytest.fail("로그 fixture가 제한 시간 내에 준비되지 않았습니다.")
    try:
        run("up", "-d")
        endpoint = "http://" + run("port", "victorialogs", "9428")
        def rows():
            query = urlencode({"query": 'service:="backend"', "start": "1h", "limit": 500})
            with urlopen(endpoint + "/select/logsql/query?" + query, timeout=3) as response:
                return [json.loads(line) for line in response.read().splitlines()]
        first = eventually(rows)
        assert first[0]["validation_field"] == "item_id"
        assert first[0]["validation_reason"] == "duplicate_item_id"
        first_container = first[0]["container_id"]
        run("up", "-d", "--force-recreate", "app")
        eventually(lambda: any(row.get("container_id") != first_container for row in rows()))
        assert any(row["container_id"] == first_container for row in rows())
        run("stop", "victorialogs")
        time.sleep(3)
        run("exec", "-T", "app", "sh", "-c", "echo '{\"level\":\"info\",\"message\":\"buffer-fixture\"}' > /proc/1/fd/1")
        time.sleep(2)
        run("restart", "vector")
        run("start", "victorialogs")
        eventually(lambda: any(row.get("_msg") == "buffer-fixture" for row in rows()))
        run("up", "-d", "--force-recreate", "victorialogs")
        endpoint = "http://" + run("port", "victorialogs", "9428")
        assert eventually(lambda: any(row["container_id"] == first_container for row in rows()))
    finally:
        # 이 시험이 생성한 무작위 프로젝트만 정리한다. 운영 볼륨은 참조하지 않는다.
        subprocess.run([*base, "down", "--volumes", "--remove-orphans"], capture_output=True, timeout=60)
