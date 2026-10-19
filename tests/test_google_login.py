"""실제 인증값과 네트워크 없이 Google 로그인·JWT·세션 흐름을 검증한다."""

import asyncio
import hashlib
import base64
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch

import pytest
from authlib.jose import JsonWebKey, JsonWebToken

from backend.access.context import AccessError
from backend.access.google import GoogleLogin
from backend.access.runtime import service_factory
from backend.access.service import PublicService
from backend.knowledge.runtime import KnowledgeService
from backend.server.app import MagiServer
from gateway.app import create_app
from test_knowledge_postgres import store


def test_google_authorization_uses_only_openid_and_pkce():
    google=GoogleLogin('fake-client','fake-value','https://magi.example/auth/google/callback')
    assert google.available
    verifier='v'*43
    url=google.authorize('fake-state','fake-nonce',verifier)
    query=parse_qs(urlsplit(url).query)
    assert urlsplit(url).netloc=='accounts.google.com'
    assert query['scope']==['openid'] and query['response_type']==['code']
    assert query['state']==['fake-state'] and query['nonce']==['fake-nonce']
    assert query['redirect_uri']==['https://magi.example/auth/google/callback']
    assert query['code_challenge_method']==['S256']
    assert query['code_challenge']==[base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()]
    assert query['include_granted_scopes']==['false']
    assert 'client_secret' not in query and 'code_verifier' not in query


@pytest.mark.parametrize('origin,local,allowed',[
    ('http://localhost:5000',True,True),('http://localhost:5000',False,False),
    ('http://example.com',True,False),('http://localhost.example.com',True,False),
    ('http://localhost:5000/path',True,False),('http://user@localhost:5000',True,False),
    ('https://magi.example',False,True),('https://magi.example',True,False),
])
def test_local_login_origin_is_explicit_and_local_only(origin,local,allowed):
    from protocol.web_config import login_origin
    if allowed:
        assert login_origin(origin,local)==origin
    else:
        with pytest.raises(ValueError):login_origin(origin,local)


def test_local_login_gateway_rejects_remote_clients_and_proxy():
    settings={'TESTING':True,'MAGI_PUBLIC_MODE':True,'MAGI_LOCAL_LOGIN':True,'MAGI_PUBLIC_ORIGIN':''}
    app=create_app(settings)
    assert app.config['MAGI_PUBLIC_ORIGIN']=='http://localhost:5000'
    with app.test_client() as browser:
        assert browser.get('/',base_url='http://localhost:5000',environ_overrides={'REMOTE_ADDR':'192.0.2.1'}).status_code==403
    with pytest.raises(ValueError):create_app({**settings,'MAGI_PROXY_HOPS':1})


@pytest.mark.parametrize('host',['127.0.0.1:5000'])
def test_local_login_redirects_loopback_alias_to_localhost(host):
    app=create_app({'TESTING':True,'MAGI_PUBLIC_MODE':True,'MAGI_LOCAL_LOGIN':True,'MAGI_PUBLIC_ORIGIN':''})
    with app.test_client() as browser:
        response=browser.get('/?next=jobs',base_url='http://'+host)
        assert response.status_code==307
        assert response.headers['Location']=='http://localhost:5000/?next=jobs'
        assert browser.get('/',base_url='http://localhost:5000').status_code==200
        assert browser.get('/',base_url='http://untrusted.example').status_code==400
        assert browser.get('/',base_url='http://'+host,environ_overrides={'REMOTE_ADDR':'192.0.2.1'}).status_code==403


def test_login_without_subject_pepper_fails_before_oauth():
    google=Mock(available=True)
    manager=SimpleNamespace(knowledge=SimpleNamespace(store=Mock()))
    service=PublicService(manager,google=google)
    service.access=Mock()
    assert service.invoke({'method':'auth.info','params':{}},Mock())['login_available'] is False
    for method in ('auth.start','auth.callback'):
        with pytest.raises(AccessError,match='MAGI_SUBJECT_PEPPER'):
            service.invoke({'method':method,'params':{}},Mock())
    service.access.begin_login.assert_not_called()
    service.access.consume_login.assert_not_called()
    google.authorize.assert_not_called()
    google.subject.assert_not_called()


def test_runtime_local_login_defaults_to_localhost():
    env={'MAGI_LOCAL_LOGIN':'1','GOOGLE_OAUTH_ID':'fake-id','GOOGLE_OAUTH_SECRET':'fake-secret','MAGI_SUBJECT_PEPPER':'fake-pepper'}
    manager=SimpleNamespace(knowledge=SimpleNamespace(store=Mock()))
    with patch('backend.access.runtime.os.environ',env):service=service_factory(manager)
    assert service.google.available
    assert service.google.redirect_uri=='http://localhost:5000/auth/google/callback'
    query=parse_qs(urlsplit(service.google.authorize('state','nonce','v'*43)).query)
    assert query['redirect_uri']==['http://localhost:5000/auth/google/callback']


@pytest.fixture
def provider_response(monkeypatch):
    # 테스트 전용 서명 키는 메모리에서만 생성하며 파일이나 로그에 기록하지 않는다.
    key=JsonWebKey.generate_key('RSA',2048,is_private=True,options={'kid':'test'})
    public=key.as_dict(is_private=False)
    keys=Mock(); keys.json.return_value={'keys':[public]}
    get=Mock(return_value=keys)
    monkeypatch.setattr('requests.get',get)
    google=GoogleLogin('fake-client','fake-value','https://magi.example/auth/google/callback')
    exchange=Mock()
    session=Mock(); session.__enter__=Mock(return_value=session); session.__exit__=Mock(return_value=False)
    session.fetch_token=exchange
    monkeypatch.setattr(google,'_client',Mock(return_value=session))
    def issue(changes=None,signing_key=None,remove=()):
        now=int(time.time())
        payload={'iss':'https://accounts.google.com','aud':'fake-client','sub':'opaque-google-subject',
                 'iat':now,'exp':now+300,'nonce':'fake-nonce',**(changes or {})}
        for field in remove:payload.pop(field,None)
        token=JsonWebToken(['RS256']).encode({'alg':'RS256','kid':'test'},payload,signing_key or key).decode()
        exchange.return_value={'id_token':token,'scope':'openid email profile'}
        return google,exchange,get
    return issue


def test_valid_google_token_uses_only_subject(provider_response,caplog):
    google,exchange,get=provider_response({'email':'fake@example.invalid','name':'테스트 사용자','picture':'https://example.invalid/photo'})
    assert google.subject('fake-code','fake-nonce','fake-verifier')=='opaque-google-subject'
    exchange.assert_called_once_with('https://oauth2.googleapis.com/token',code='fake-code',code_verifier='fake-verifier',timeout=10)
    get.assert_called_once_with('https://www.googleapis.com/oauth2/v3/certs',timeout=10)
    assert 'fake@example.invalid' not in caplog.text and '테스트 사용자' not in caplog.text


@pytest.mark.parametrize('changes',[
    {'iss':'https://wrong.example'}, {'aud':'wrong-client'}, {'exp':1}, {'nonce':'wrong-nonce'},
    {'azp':'wrong-client'}, {'sub':''}, {'sub':123}, {'sub':'x'*256},
])
def test_google_rejects_invalid_claims(provider_response,changes):
    google,_,_=provider_response(changes)
    with pytest.raises(AccessError,match='Google 로그인 결과'):google.subject('fake-code','fake-nonce','fake-verifier')


def test_google_rejects_missing_nonce_and_bad_signature(provider_response):
    google,_,_=provider_response(remove=('nonce',))
    with pytest.raises(AccessError):google.subject('fake-code','fake-nonce','fake-verifier')
    other=JsonWebKey.generate_key('RSA',2048,is_private=True,options={'kid':'test'})
    google,_,_=provider_response(signing_key=other)
    with pytest.raises(AccessError):google.subject('fake-code','fake-nonce','fake-verifier')


@pytest.mark.parametrize('values,expected',[
    ({'GOOGLE_OAUTH_ID':'new-id','GOOGLE_OAUTH_SECRET':'new-secret','MAGI_GOOGLE_CLIENT_ID':'old-id','MAGI_GOOGLE_CLIENT_SECRET':'old-secret'},('new-id','new-secret',True)),
    ({'MAGI_GOOGLE_CLIENT_ID':'old-id','MAGI_GOOGLE_CLIENT_SECRET':'old-secret'},('old-id','old-secret',True)),
    ({'GOOGLE_OAUTH_ID':'new-id','MAGI_GOOGLE_CLIENT_SECRET':'old-secret'},('new-id','',False)),
])
def test_runtime_reads_configured_names_without_mixing_pairs(values,expected):
    env={'MAGI_PUBLIC_ORIGIN':'https://magi.example','MAGI_SUBJECT_PEPPER':'fake-pepper',**values}
    manager=SimpleNamespace(knowledge=SimpleNamespace(store=Mock()))
    with patch('backend.access.runtime.os.environ',env):service=service_factory(manager)
    assert (service.google.client_id,service.google.client_secret,service.google.available)==expected


@pytest.mark.parametrize('local_login',[False,True])
def test_mock_google_to_server_session_cookie_and_logout(store,tmp_path,local_login):
    origin='http://localhost:5000' if local_login else 'https://magi.example'
    cookie_name='magi_local_session' if local_login else '__Host-magi_session'
    async def scenario():
        google=GoogleLogin('fake-client','fake-value',origin+'/auth/google/callback',local_login=local_login)
        google.subject=Mock(return_value='opaque-subject')
        backend=MagiServer(tmp_path,knowledge=KnowledgeService(store),public=lambda m:PublicService(m,google=google,pepper='fake-pepper'))
        class Client:
            def __init__(self,url):self.context={}
            def call(self,method,params=None):
                response=json.loads(backend._dispatch({'request_id':'test','method':method,'params':params or {},**self.context}))
                if 'error' in response:
                    from gateway.magi_client import MagiClientError
                    codes={'unauthorized':401,'forbidden':403,'unavailable':503}
                    raise MagiClientError(response['error']['message'],status=codes.get(response['error']['code'],400))
                return response['result']
        app=create_app({'TESTING':True,'MAGI_PUBLIC_MODE':True,'MAGI_PUBLIC_ORIGIN':origin,'MAGI_LOCAL_LOGIN':local_login,'MAGI_CLIENT_FACTORY':Client})
        try:
            with app.test_client() as browser:
                assert browser.get('/api/auth/info',base_url=origin).json['login_available']
                start=browser.get('/auth/google/start',base_url=origin)
                assert start.status_code==302
                query=parse_qs(urlsplit(start.location).query)
                state=query['state'][0]
                # 브라우저 연결 값이 없는 콜백과 state 재사용은 거절한다.
                with app.test_client() as foreign:
                    assert foreign.get('/auth/google/callback',query_string={'state':state,'code':'fake-code'},base_url=origin).status_code==401
                callback=browser.get('/auth/google/callback',query_string={'state':state,'code':'fake-code'},base_url=origin)
                assert callback.status_code==302
                cookie=next(value for value in callback.headers.getlist('Set-Cookie') if value.startswith(cookie_name+'='))
                assert all(flag in cookie for flag in ('HttpOnly','SameSite=Lax','Max-Age=86400','Path=/'))
                assert ('Secure' in cookie) == (not local_login)
                assert ('Strict-Transport-Security' in callback.headers) == (not local_login)
                assert 'fake-code' not in callback.location and 'opaque-subject' not in cookie
                me=browser.get('/api/me',base_url=origin).json
                assert set(me)=={'id','role','expires_at','csrf'}
                assert google.subject.call_count==1
                google.subject.assert_called_with('fake-code',query['nonce'][0],__import__('unittest.mock',fromlist=['ANY']).ANY)
                replay=browser.get('/auth/google/callback',query_string={'state':state,'code':'fake-code'},base_url=origin)
                assert replay.status_code==401 and google.subject.call_count==1
                with store.transaction() as c:
                    row=c.execute('SELECT subject_hash FROM magi_users WHERE id=%s',(me['id'],)).fetchone()
                    assert row['subject_hash']!='opaque-subject'
                assert browser.post('/api/logout',json={},base_url=origin,headers={'Origin':'https://wrong.example','X-CSRF-Token':me['csrf']}).status_code==403
                logout=browser.post('/api/logout',json={},base_url=origin,headers={'Origin':origin,'X-CSRF-Token':me['csrf']})
                assert logout.status_code==200
                assert browser.get('/api/me',base_url=origin).status_code==401
        finally:backend.manager.close()
    asyncio.run(scenario())
