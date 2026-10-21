"""이전 설정을 조용히 무시해 인증·저장 방식을 바꾸지 않는다."""

import os


ACTIVE_SETTINGS = (
    'PUBLIC_MODE', 'PUBLIC_ORIGIN', 'LOCAL_LOGIN', 'PROXY_HOPS', 'SERVER_URL',
    'INTERNAL_KEY', 'SUBJECT_PEPPER', 'CONTAINER', 'DATA_DIR', 'DB_HOST', 'DB_PORT',
    'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_SSLMODE', 'EMBEDDING_MODEL_PATH',
    'EMBEDDING_DEVICE', 'DEPLOY_ROOT', 'MODEL_ROOT', 'HTTP_PORT', 'HTTPS_PORT',
    'BACKEND_IMAGE', 'GATEWAY_IMAGE', 'CADDY_IMAGE', 'CI_POSTGRES', 'TEST_NODE_MODULES',
    'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET',
)


def require_current_environment():
    # 값은 읽지 않는다. 폐기된 모델·가격 설정은 이 목록에 포함하지 않는다.
    if any('MAGI_' + name in os.environ for name in ACTIVE_SETTINGS):
        raise ValueError('이전 MAGI_ 환경 변수 이름이 있습니다. 새 이름으로 변경한 뒤 시작하세요.')
