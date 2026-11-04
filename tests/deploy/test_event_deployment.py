"""운영 비밀 없이 단일 스택·브로커 설정·readiness를 검증한다."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
from threading import Event
from types import SimpleNamespace

import pytest
import yaml
from deploy.artifacts import RABBITMQ, SCAN_ROLES
from protocol.amqp import BrokerSettings

ROOT = Path(__file__).resolve().parents[2]
FAKE = {'RABBITMQ_HOST': 'rabbitmq', 'RABBITMQ_PORT': '5672', 'RABBITMQ_VHOST': '/',
        'RABBITMQ_USER': 'fixture', 'RABBITMQ_PASSWORD': 'fake:/@?# password'}


def test_connection_parameters_do_not_require_url_encoding():
    settings = BrokerSettings.from_mapping(FAKE)
    params = settings.parameters()
    assert params.host == 'rabbitmq' and params.port == 5672 and params.virtual_host == '/'
    assert params.credentials.password == FAKE['RABBITMQ_PASSWORD']
    assert FAKE['RABBITMQ_PASSWORD'] not in repr(settings)


@pytest.mark.parametrize('key', list(FAKE))
def test_required_settings_fail_without_echoing_values(key):
    values = {k: v for k, v in FAKE.items() if k != key}
    with pytest.raises(ValueError) as caught:
        BrokerSettings.from_mapping(values)
    assert FAKE['RABBITMQ_PASSWORD'] not in str(caught.value)


@pytest.mark.parametrize('port', ['0', '65536', 'invalid'])
def test_invalid_port_has_fixed_error(port):
    with pytest.raises(ValueError, match='포트 설정'):
        BrokerSettings.from_mapping({**FAKE, 'RABBITMQ_PORT': port})


def test_portainer_stack_and_ci_share_pinned_broker():
    compose = yaml.safe_load((ROOT / 'deploy/compose.portainer.yaml').read_text(encoding='utf-8'))
    verify = yaml.safe_load((ROOT / '.github/workflows/verify.yml').read_text(encoding='utf-8'))
    services = compose['services']
    broker = services['rabbitmq']
    assert broker['image'] == verify['jobs']['verify']['services']['rabbitmq']['image'] == RABBITMQ
    assert '@sha256:' in RABBITMQ and 'management' not in RABBITMQ
    assert 'ports' not in broker and broker['networks'] == ['events']
    assert broker['mem_limit'] == broker['memswap_limit'] == '512m'
    assert 'user' not in broker and not broker.get('read_only')
    assert broker['volumes'] == ['rabbitmq-data:/var/lib/rabbitmq']
    assert compose['networks']['events'] == {'internal': True}
    assert set(services['caddy']['networks']) == {'events', 'magi-db', 'logs'}
    for role in ('backend', 'gateway'):
        assert services[role]['network_mode'] == 'service:caddy'
        assert services[role]['depends_on']['rabbitmq'] == {'condition': 'service_healthy'}
        assert services[role]['environment']['RABBITMQ_HOST'] == 'rabbitmq'
        assert services[role]['environment']['RABBITMQ_PASSWORD'] == broker['environment']['RABBITMQ_DEFAULT_PASS']
    assert 'rabbitmq' in SCAN_ROLES
    workflow = yaml.safe_load((ROOT / '.github/workflows/build-arm64.yml').read_text(encoding='utf-8'))
    step = next(s for s in workflow['jobs']['build']['steps'] if s.get('name') == 'Scan RabbitMQ fixable critical vulnerabilities')
    assert step['with']['image-ref'] == RABBITMQ and step['with']['exit-code'] == '1'
    assert step['env']['TRIVY_PLATFORM'] == 'linux/arm64'
    assert not (ROOT / 'deploy/compose.rabbitmq.yaml').exists()
    assert not (ROOT / 'deploy/compose.events.yaml').exists()


def test_render_compose_with_fake_values_and_reject_missing_account(tmp_path):
    executable = shutil.which('docker')
    if executable is None:
        if os.environ.get('CI_RABBITMQ') == '1':
            pytest.fail('CI에는 Docker Compose 렌더링 도구가 필요합니다.')
        pytest.skip('로컬 Docker가 없어 Compose 렌더링은 CI에서 수행합니다.')
    values = {name: 'fake-value' for name in ('CADDY_IMAGE', 'BACKEND_IMAGE', 'GATEWAY_IMAGE', 'INTERNAL_KEY', 'OPENAI_API_KEY',
        'GOOGLE_OAUTH_ID', 'GOOGLE_OAUTH_SECRET', 'SUBJECT_PEPPER', 'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'RABBITMQ_USER', 'RABBITMQ_PASSWORD')}
    values.update(PUBLIC_ORIGIN='https://magi.example', DEPLOY_ROOT='/fixture/deploy', MODEL_ROOT='/fixture/model')
    fixture = tmp_path / 'fixture.vars'
    # Docker가 로컬 인증 저장소나 .env를 자동 탐색하지 않게 입력을 격리한다.
    environment = {'PATH': os.environ.get('PATH', ''), 'DOCKER_CONFIG': str(tmp_path / 'docker-config')}
    if os.name == 'nt':
        environment['SYSTEMROOT'] = os.environ.get('SYSTEMROOT', r'C:\Windows')
    command = [executable, 'compose', '--env-file', str(fixture), '--project-directory', str(tmp_path),
               '-f', str(ROOT / 'deploy/compose.portainer.yaml'), 'config', '--format', 'json']
    def render(mapping):
        fixture.write_text(''.join(f'{k}={v}\n' for k, v in mapping.items()), encoding='utf-8')
        return subprocess.run(command, env=environment, capture_output=True, text=True, timeout=30)
    result = render(values)
    assert result.returncode == 0, '가짜 설정으로 Compose를 렌더링하지 못했습니다.'
    config = json.loads(result.stdout)
    assert not config['services']['rabbitmq'].get('ports')
    assert config['networks']['events']['internal']
    for missing in ('RABBITMQ_USER', 'RABBITMQ_PASSWORD'):
        assert render({k: v for k, v in values.items() if k != missing}).returncode != 0


def test_backend_readiness_requires_ready_amqp_channel():
    from backend.server.app import Server
    ready = Event()
    @contextmanager
    def connect(**kwargs):
        yield SimpleNamespace(execute=lambda *a: SimpleNamespace(fetchone=lambda: {'ok': 1}))
    server = object.__new__(Server)
    server.internal_key = 'fake-internal'
    server.manager = SimpleNamespace(closed=False, progress_publisher=SimpleNamespace(broker=SimpleNamespace(ready=ready)),
        knowledge=SimpleNamespace(store=SimpleNamespace(connect=connect, config=SimpleNamespace(connection={}))))
    packet = {'request_id': 'health', 'method': 'health.check', 'params': {}}
    assert 'error' in json.loads(server._dispatch_logged(packet))
    ready.set()
    assert json.loads(server._dispatch_logged(packet))['result'] == {'ready': True}
    ready.clear()
    assert 'error' in json.loads(server._dispatch_logged(packet))


def test_gateway_readiness_and_liveness_are_separate():
    from gateway.app import create_app
    class Client:
        def __init__(self, url):
            pass
        def call(self, method):
            return {'ready': True}
    app = create_app({'TESTING': True, 'PUBLIC_MODE': False, 'CLIENT_FACTORY': Client})
    ready = Event()
    app.extensions['progress_hub'] = SimpleNamespace(broker=SimpleNamespace(ready=ready))
    with app.test_client() as client:
        assert client.get('/health/live').status_code == 200
        assert client.get('/health/ready').status_code == 503
        ready.set()
        assert client.get('/health/ready').status_code == 200
        ready.clear()
        assert client.get('/health/ready').status_code == 503
        assert client.get('/health/live').status_code == 200


def test_gateway_initializes_one_shared_connection_before_browser(monkeypatch):
    import atexit
    from gateway.app import create_app
    settings = BrokerSettings.from_mapping(FAKE)
    created = []
    class Hub:
        def __init__(self, value):
            created.append(value)
        def close(self):
            pass
    monkeypatch.setattr('gateway.progress.ProgressHub', Hub)
    monkeypatch.setattr(atexit, 'register', lambda *args: None)
    app = create_app({'TESTING': True, 'PUBLIC_MODE': False, 'BROKER_SETTINGS': settings})
    assert created == [settings]
    assert isinstance(app.extensions['progress_hub'], Hub)


def test_container_requires_broker_settings_without_exposing_values(monkeypatch):
    from protocol import deployment
    environment = {**FAKE, 'CONTAINER': '1', 'PUBLIC_MODE': '1', 'LOCAL_LOGIN': '0',
        'PUBLIC_ORIGIN': 'https://magi.example', 'PROXY_HOPS': '1', 'INTERNAL_KEY': 'fake-internal'}
    monkeypatch.setattr(deployment, 'os', SimpleNamespace(environ=environment))
    deployment.validate_container('gateway')
    environment.pop('RABBITMQ_PASSWORD')
    with pytest.raises(ValueError, match='RABBITMQ_PASSWORD') as caught:
        deployment.validate_container('gateway')
    assert 'fake-internal' not in str(caught.value)
