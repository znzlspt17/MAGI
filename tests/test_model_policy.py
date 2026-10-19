"""환경 설정 없는 접수와 단일 모델·보수적 비용 경계를 검증한다."""
import asyncio
import json
from decimal import Decimal
from unittest.mock import Mock

import pytest

from backend.config import MagiConfig, AGENT_KEYS
from backend.errors import MagiError
from backend.model_policy import MODEL, MAX_OUTPUT_TOKENS, default_prices
from backend.models import ModelRoute, CompletionResult
from backend.access.billing import Meter
from backend.access.context import AccessError, METER
from backend.access.service import PublicService
from backend.knowledge.runtime import KnowledgeService
from backend.providers.llm_provider import OpenAIProvider
from backend.server.app import MagiServer
from test_public_service import store, account


def test_legacy_environment_cannot_change_model_or_prices(monkeypatch):
    monkeypatch.setenv('MAGI_SPEC_OPENAI_MODEL','other-model')
    monkeypatch.setenv('MAGI_MODEL_PRICES','not-json')
    for config in (MagiConfig.default(),MagiConfig.from_dict({})):
        assert set(config.model_routing)==set(AGENT_KEYS)
        assert {route.model for route in config.model_routing.values()}=={MODEL}
    from backend.access.runtime import service_factory
    monkeypatch.setenv('MAGI_LOCAL_LOGIN','1')
    monkeypatch.setenv('MAGI_PUBLIC_ORIGIN','http://localhost:5000')
    assert service_factory(Mock()).prices==default_prices()


def test_configuration_and_provider_reject_other_models_before_sdk(monkeypatch,tmp_path):
    path=tmp_path/'config.json'
    path.write_text(json.dumps({'models':{'compiler':{'model':'other-model'}}}))
    with pytest.raises(MagiError,match=MODEL):MagiConfig.from_file(path)
    config=MagiConfig.default()
    config.model_routing['compiler']=ModelRoute(provider='openai',model='other-model')
    with pytest.raises(MagiError,match=MODEL):config.validate()
    sdk=Mock();monkeypatch.setattr('backend.providers.llm_provider.OpenAI',sdk)
    # API 키 확인보다 모델 검사가 먼저 실행되어 잘못된 모델로 외부 호출하지 않는다.
    with pytest.raises(MagiError,match=MODEL):OpenAIProvider().complete_result([],model='other-model')
    sdk.assert_not_called()


@pytest.mark.parametrize('tokens,expected',[
    (272_000,Decimal('0.03405000')),
    (272_001,Decimal('0.06807525')),
])
def test_cost_boundary_cache_write_and_no_cache_discount(tokens,expected):
    access=Mock()
    meter=Meter(access,'user','job',1,default_prices())
    assert meter.maximum(MODEL)==Decimal('0.35850000')
    meter.settle('call',MODEL,CompletionResult(text='test',input_tokens=tokens,output_tokens=100,cached_tokens=tokens))
    access.settle.assert_called_once_with('call',expected)
    access.reset_mock()
    with pytest.raises(AccessError):
        meter.settle('call',MODEL,CompletionResult(text='test',input_tokens=10,output_tokens=MAX_OUTPUT_TOKENS+1))
    access.settle.assert_called_once_with('call')


def test_default_policy_admits_and_starts_once_without_price_environment(store,tmp_path,monkeypatch):
    monkeypatch.delenv('MAGI_MODEL_PRICES',raising=False)
    monkeypatch.delenv('MAGI_SPEC_OPENAI_MODEL',raising=False)
    async def scenario():
        server=MagiServer(tmp_path,knowledge=KnowledgeService(store),public=lambda manager:PublicService(manager,pepper='fake-pepper'))
        server.manager.executor.submit=Mock()
        try:
            access=server.public.access
            sid,user=account(access,'owner')
            request={'request_id':'test','method':'generate','params':{'request':'Test requirement'},'session':sid,'csrf':user['csrf'],'idempotency_key':'test-policy-request'}
            first=json.loads(server._dispatch(request))
            assert 'result' in first,first
            assert json.loads(server._dispatch(request))==first
            server.manager.executor.submit.assert_called_once()
            jid=first['result']['id']
            def run(ident,action,payload):
                meter=METER.get()
                reservation=meter.reserve(MODEL)
                meter.settle(reservation,MODEL,CompletionResult(text='test',input_tokens=10,output_tokens=5))
                server.manager.jobs[ident]['status']='NEEDS_USER_INPUT'
            server.manager._run=run
            server.public.worker(jid,'generate',None)
            with store.transaction() as c:
                calls=c.execute('SELECT model,reserved,actual,state FROM magi_cost_calls WHERE job_id=%s',(jid,)).fetchall()
            assert len(calls)==1 and calls[0]['model']==MODEL and calls[0]['state']=='settled'
            assert Decimal(str(calls[0]['reserved']))==Decimal('0.35850000')
            assert Decimal(str(calls[0]['actual']))==Decimal('0.00000375')
        finally: server.manager.close()
    asyncio.run(scenario())
