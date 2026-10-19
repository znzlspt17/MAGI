"""게이트웨이와 백엔드가 공유하는 공개·로컬 로그인 주소 규칙."""

from urllib.parse import urlsplit


def login_origin(origin, local_login=False):
    origin = origin or ('http://localhost:5000' if local_login else '')
    parsed = urlsplit(origin)
    try:
        valid_port = parsed.port is None or 1 <= parsed.port <= 65535
    except ValueError:
        valid_port = False
    valid = (bool(parsed.hostname) and valid_port and not parsed.path and not parsed.query
             and not parsed.fragment and parsed.username is None and parsed.password is None)
    if local_login:
        valid = valid and parsed.scheme == 'http' and parsed.hostname == 'localhost'
    else:
        valid = valid and parsed.scheme == 'https'
    if not valid:
        raise ValueError('MAGI_PUBLIC_ORIGIN에는 공개 HTTPS 주소 또는 로컬 로그인 모드의 http://localhost 주소가 필요합니다.')
    return origin
