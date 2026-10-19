"""접수 전 설정 거부, 오류 응답, 통신 실패의 안내와 로그를 구분한다."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock

import pytest

from backend.access.service import PublicService
from backend.knowledge.runtime import KnowledgeService
from backend.server.app import MagiServer
from gateway.app import create_app
from gateway.magi_client import MagiClient, MagiClientError
from test_public_service import store, account


def test_missing_price_is_rejected_before_admission_and_logged(store,tmp_path,monkeypatch):
    async def scenario():
        server=MagiServer(tmp_path,knowledge=KnowledgeService(store),public=lambda manager:PublicService(manager,prices={},pepper='fake-pepper'))
        warning=Mock()
        monkeypatch.setattr('backend.server.app.LOGGER.warning',warning)
        server.manager.executor.submit=Mock()
        try:
            sid,user=account(server.public.access,'test-owner')
            response=json.loads(server._dispatch({'request_id':'test','method':'generate','params':{'request':'private test request'},'session':sid,'csrf':user['csrf'],'idempotency_key':'test-request-key'}))
            assert response['error']['code']=='configuration'
            assert '모델 단가' in response['error']['message']
            assert not server.manager.jobs
            assert not server.public.access.status(user['id'])['busy']
            assert server.public.access.usage(user['id'])['runs']==0
            server.manager.executor.submit.assert_not_called()
            assert warning.call_args.args[2]=='configuration'
            assert 'private test request' not in str(warning.call_args)
        finally: server.manager.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('code,message,uncertain',[
    ('configuration','모델 단가와 검증된 문맥 상한을 설정해야 합니다.',False),
    ('unavailable','요청을 처리하지 못했습니다.',True),
])
def test_received_backend_error_is_not_a_missing_response(monkeypatch,code,message,uncertain):
    from gateway import magi_client
    socket=MagicMock()
    socket.__enter__.return_value=socket
    socket.recv.return_value=json.dumps({'request_id':'test','error':{'code':code,'message':message}})
    monkeypatch.setattr(magi_client,'connect',Mock(return_value=socket))
    monkeypatch.setattr(magi_client,'uuid4',lambda:SimpleNamespace(hex='test'))
    client=MagiClient('ws://127.0.0.1:8765')
    with pytest.raises(MagiClientError) as caught: client.call('generate',{'request':'test'})
    assert caught.value.response_received and caught.value.uncertain==uncertain
    class Client:
        def __init__(self,url): pass
        def call(self,*args): raise caught.value
    app=create_app({'TESTING':True,'MAGI_PUBLIC_MODE':False,'MAGI_CLIENT_FACTORY':Client})
    log=Mock(); monkeypatch.setattr(app.logger,'warning',log)
    with app.test_client() as browser:
        response=browser.post('/api/jobs',json={'request':'private test request'})
        assert response.status_code==503
        assert message in response.json['error']
        assert '응답을 받지 못했습니다' not in response.json['error']
        assert response.json['request_id']
    log.assert_called_once()
    assert 'private test request' not in str(log.call_args)


def test_unexpected_public_exception_is_logged_without_exposing_details(tmp_path,monkeypatch):
    async def scenario():
        server=MagiServer(tmp_path)
        log=Mock(); monkeypatch.setattr('backend.server.app._log_exception',log)
        server.public=SimpleNamespace(invoke=Mock(side_effect=RuntimeError('fake-sensitive-detail')))
        try:
            response=server._dispatch({'request_id':'test','method':'generate','params':{}})
            assert 'fake-sensitive-detail' not in response
            log.assert_called_once()
            assert log.call_args.kwargs['method']=='generate'
        finally: server.manager.close()
    asyncio.run(scenario())


def test_transport_failure_keeps_uncertain_banner_and_logs(monkeypatch):
    class Client:
        def __init__(self,url): pass
        def call(self,*args):
            raise MagiClientError('작업 서버에 연결할 수 없습니다.',uncertain=True) from TimeoutError('fake-sensitive-detail')
    app=create_app({'TESTING':True,'MAGI_PUBLIC_MODE':False,'MAGI_CLIENT_FACTORY':Client})
    log=Mock();monkeypatch.setattr(app.logger,'warning',log)
    with app.test_client() as browser:
        response=browser.post('/api/jobs',json={'request':'private test request'})
        assert '응답을 받지 못했습니다' in response.json['error']
    assert 'TimeoutError' in str(log.call_args)
    assert 'fake-sensitive-detail' not in str(log.call_args)
