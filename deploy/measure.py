"""Pi의 컨테이너 cgroup 메모리와 OOM·재시작을 측정한다. 환경값은 조회하지 않는다."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import time


LIMIT_BYTES = 6_000_000_000


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, timeout=15).strip()


def identity(container):
    # 전체 inspect 결과에는 환경값이 있으므로 허용된 필드만 요청한다.
    raw = docker('inspect', '--format',
                 '{{json .Id}} {{json .State.Status}} {{json .State.OOMKilled}} {{json .RestartCount}}', container)
    ident, status, oom, restarts = raw.split()
    return {'id': json.loads(ident), 'status': json.loads(status),
            'oom': json.loads(oom), 'restarts': int(restarts)}


def cgroup(ident):
    if not re.fullmatch(r'[0-9a-f]{64}', ident):
        raise ValueError('컨테이너 ID가 올바르지 않습니다.')
    candidates = (Path('/sys/fs/cgroup/system.slice') / f'docker-{ident}.scope',
                  Path('/sys/fs/cgroup/docker') / ident)
    for path in candidates:
        if (path / 'memory.current').is_file():
            return path
    raise RuntimeError('rootful Docker의 cgroup v2 메모리 경로를 확인하세요.')


def memory(ident):
    # docker stats는 Linux 파일 캐시를 빼므로 cgroup 값을 직접 읽는다.
    # 호스트 cgroup만 읽으므로 shell이 없는 Portainer 이미지도 측정한다.
    root = cgroup(ident)
    events = dict(line.split() for line in (root / 'memory.events').read_text().splitlines())
    cpu = dict(line.split() for line in (root / 'cpu.stat').read_text().splitlines())
    return {'bytes': int((root / 'memory.current').read_text()),
            'oom_kills': int(events['oom_kill']), 'cpu_usage_usec': int(cpu['usage_usec'])}


def measure(containers, seconds, interval, output):
    if seconds < 1 or interval < 1 or not containers or len(set(containers)) != len(containers):
        raise ValueError('서로 다른 컨테이너와 양수 측정 시간을 지정하세요.')
    if output.exists():
        raise ValueError('기존 측정 결과를 덮어쓰지 않습니다.')
    initial = {name: identity(name) for name in containers}
    initial_memory = {name: memory(state['id']) for name, state in initial.items()}
    deadline = time.monotonic() + seconds
    peak = 0
    valid = True
    with output.open('x', encoding='utf-8') as stream:
        while True:
            samples = {}
            for name in containers:
                state = identity(name)
                state.update(memory(state['id']))
                samples[name] = state
                valid &= (state['status'] == 'running' and not state['oom']
                          and state['id'] == initial[name]['id']
                          and state['restarts'] == initial[name]['restarts']
                          and state['oom_kills'] == initial_memory[name]['oom_kills'])
            total = sum(item['bytes'] for item in samples.values())
            peak = max(peak, total)
            valid &= total <= LIMIT_BYTES
            thermal = Path('/sys/class/thermal/thermal_zone0/temp')
            temperature = int(thermal.read_text()) / 1000 if thermal.is_file() else None
            stream.write(json.dumps({'time': time.time(), 'total_bytes': total,
                                    'temperature_c': temperature, 'containers': samples}) + '\n')
            stream.flush()
            if time.monotonic() >= deadline:
                break
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
        summary = {'within_6GB_no_restart': bool(valid), 'peak_bytes': peak,
                   'seconds': seconds, 'interval': interval, 'sampled_not_continuous': True}
        stream.write(json.dumps({'summary': summary}) + '\n')
    print(json.dumps(summary))
    return bool(valid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--containers', nargs='+', required=True, help='DB·Portainer·agent·앱 등 운영 중인 전체 컨테이너')
    parser.add_argument('--seconds', type=int, default=3600)
    parser.add_argument('--interval', type=int, default=5)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if measure(args.containers, args.seconds, args.interval, args.output) else 1)


if __name__ == '__main__':
    main()
