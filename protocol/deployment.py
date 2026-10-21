"""컨테이너의 필수 설정 검증과 원문을 출력하지 않는 상태 점검."""

import http.client
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

from protocol.web_config import login_origin


def validate_container(role):
    if os.environ.get('MAGI_CONTAINER') != '1':
        return
    if os.environ.get('MAGI_PUBLIC_MODE') != '1' or os.environ.get('MAGI_LOCAL_LOGIN', '0') != '0':
        raise ValueError('컨테이너 배포는 공개 HTTPS 모드가 필요합니다.')
    login_origin(os.environ.get('MAGI_PUBLIC_ORIGIN', ''), False)
    required = ['MAGI_INTERNAL_KEY']
    if role == 'backend':
        required += ['OPENAI_API_KEY', 'GOOGLE_OAUTH_ID', 'GOOGLE_OAUTH_SECRET',
                     'MAGI_SUBJECT_PEPPER', 'MAGI_DB_HOST', 'MAGI_DB_NAME',
                     'MAGI_DB_USER', 'MAGI_DB_PASSWORD', 'MAGI_EMBEDDING_MODEL_PATH']
    elif role == 'gateway':
        if os.environ.get('MAGI_PROXY_HOPS') != '1':
            raise ValueError('컨테이너 게이트웨이에는 단일 프록시 설정이 필요합니다.')
    else:
        raise ValueError('지원하지 않는 컨테이너 역할입니다.')
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise ValueError('필수 컨테이너 설정이 누락되었습니다: ' + ', '.join(missing))
    if role == 'backend' and not Path(os.environ['MAGI_EMBEDDING_MODEL_PATH']).is_dir():
        raise ValueError('읽기 전용 모델 폴더를 마운트하세요.')


def backend_ready():
    from websockets.sync.client import connect
    key = os.environ.get('MAGI_INTERNAL_KEY', '')
    if not key:
        return False
    with connect('ws://127.0.0.1:8765', additional_headers={'X-Magi-Internal': key},
                 open_timeout=3, close_timeout=1, max_size=4096) as socket:
        socket.send(json.dumps({'request_id': 'health', 'method': 'health.check', 'params': {}}))
        reply = json.loads(socket.recv(timeout=5))
        return reply.get('request_id') == 'health' and reply.get('result') == {'ready': True}


def gateway_ready():
    connection = http.client.HTTPConnection('127.0.0.1', 5000, timeout=8)
    try:
        host = urlsplit(os.environ.get('MAGI_PUBLIC_ORIGIN', '')).netloc
        connection.request('GET', '/health/ready', headers={'Host': host})
        response = connection.getresponse()
        return response.status == 200 and json.loads(response.read(4096)) == {'ready': True}
    finally:
        connection.close()


def main():
    try:
        target = sys.argv[1] if len(sys.argv) == 2 else ''
        ready = backend_ready() if target == 'backend' else gateway_ready() if target == 'gateway' else False
    except Exception:
        ready = False
    # 예외·응답·접속 설정은 healthcheck 로그에 기록하지 않는다.
    raise SystemExit(0 if ready else 1)


if __name__ == '__main__':
    main()
