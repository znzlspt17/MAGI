"""실제 테스트 DB에서 공개 서비스의 계정·독점·비용 경계를 검증한다."""

import asyncio
from contextlib import contextmanager
from decimal import Decimal
import json
import threading
from unittest.mock import Mock

import pytest

from backend.access.context import ACTOR, AccessError
from backend.access.google import GoogleLogin
from backend.access.service import PublicService
from backend.access.store import AccessStore, day_at
from backend.access.billing import Meter
from backend.knowledge.runtime import KnowledgeService
from backend.server.app import MagiServer
from gateway.app import create_app
from gateway.magi_client import MagiClient
from test_knowledge_postgres import store
from websockets.asyncio.server import serve


@pytest.fixture
def access(store):
    return AccessStore(store,clock=lambda:1800000000)


def account(access,subject):
    sid=access.login(subject,'fake-test-pepper')
    return sid,access.session(sid)


def test_sessions_rotation_revocation_and_single_use_login(access):
    sid,user=account(access,'subject-a')
    second=access.login('subject-a','fake-test-pepper',sid)
    assert access.session(second)['id']==user['id']
    with pytest.raises(AccessError):access.session(sid)
    state,browser,nonce,verifier=access.begin_login()
    with pytest.raises(AccessError):access.consume_login(state,'different-browser')
    assert access.consume_login(state,browser)=={'nonce':nonce,'verifier':verifier}
    with pytest.raises(AccessError):access.consume_login(state,browser)
    access.clock=lambda:1800000000+86400
    with pytest.raises(AccessError):access.session(second)


def test_exclusive_wait_timeout_running_and_generation(access):
    _,a=account(access,'a'); _,b=account(access,'b')
    with access.store.transaction() as c: generation=access.acquire(c,a['id'],'job-a',count=True)
    with access.store.transaction() as c:
        with pytest.raises(AccessError):access.acquire(c,b['id'],'job-b',count=True)
    assert access.usage(b['id'])['runs']==0
    access.clock=lambda:1800000900
    assert access.status(b['id'])['busy']  # 모델 실행에는 3분 만료가 없다.
    access.finish('job-a',generation,waiting=True)
    access.clock=lambda:1800001079
    assert access.status(b['id'])['busy']
    access.clock=lambda:1800001080
    assert not access.status(b['id'])['busy']
    with access.store.transaction() as c:new=access.acquire(c,b['id'],'job-b')
    access.finish('job-a',generation)
    assert access.status(b['id'])['mine'] and new>generation


def test_daily_counts_cost_reservations_uncertain_and_midnight(access):
    _,a=account(access,'a')
    now=1800000000
    for i in range(3):
        with access.store.transaction() as c:g=access.acquire(c,a['id'],'a',count=True)
        access.finish('a',g)
    with pytest.raises(AccessError):
        with access.store.transaction() as c:access.acquire(c,a['id'],'a',count=True)
    with access.store.transaction() as c:g=access.acquire(c,a['id'],'a')
    call=access.reserve(a['id'],'a',g,'model',Decimal('1.50'))
    with pytest.raises(AccessError):access.reserve(a['id'],'a',g,'model',Decimal('.51'))
    access.settle(call)
    with pytest.raises(AccessError):access.reserve(a['id'],'a',g,'model',Decimal('.51'))
    access.clock=lambda:now+86400
    access.settle(call,Decimal('.25'))
    assert access.usage(a['id'])['runs']==0
    with access.store.transaction() as c:
        old=c.execute('SELECT spent,reserved FROM magi_daily_usage WHERE user_id=%s AND day=%s',(a['id'],day_at(now))).fetchone()
        assert Decimal(str(old['spent']))==Decimal('.25') and Decimal(str(old['reserved']))==0


def test_global_money_ceiling_and_bad_pricing(access):
    with access.store.transaction() as c:c.execute('UPDATE magi_service_settings SET daily_usd=2.5 WHERE singleton=1')
    for subject,amount in [('a','1.5'),('b','1.0')]:
        _,u=account(access,subject)
        with access.store.transaction() as c:g=access.acquire(c,u['id'],subject)
        access.reserve(u['id'],subject,g,'model',Decimal(amount))
        access.finish(subject,g)
    _,u=account(access,'c')
    with access.store.transaction() as c:g=access.acquire(c,u['id'],'c')
    with pytest.raises(AccessError):access.reserve(u['id'],'c',g,'model',Decimal('.01'))
    with pytest.raises(AccessError):Meter(access,u['id'],'c',g,{}).maximum('unknown')


def test_rls_blocks_other_jobs_nodes_artifacts_and_vectors(store,access):
    _,a=account(access,'a'); _,b=account(access,'b')
    # 테이블 소유자/슈퍼유저의 RLS 우회를 배제하고 실제 비특권 역할로 조회한다.
    with store.transaction() as c:
        c.execute('CREATE ROLE magi_test_public')
        c.execute('GRANT USAGE ON SCHEMA public TO magi_test_public')
        c.execute('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO magi_test_public')
    for user,jid in [(a,'a'*32),(b,'b'*32)]:
        store.create_project('test',jid)
        store.commit_stage({'id':jid,'owner_id':user['id'],'project_id':jid,'request':'test'},'e','spec_compile',
                           {'user_request':'test'}, {'final/FINAL_AGENT_SPEC.md':'private document'})
    original=store.transaction
    @contextmanager
    def restricted(**kwargs):
        with original(**kwargs) as c:
            c.execute('SET LOCAL ROLE magi_test_public')
            yield c
    store.transaction=restricted
    token=ACTOR.set(a)
    try:
        assert [j['id'] for j in store.jobs()]==['a'*32]
        with store.transaction() as c:
            assert not c.execute('SELECT * FROM magi_artifacts WHERE job_id=%s',('b'*32,)).fetchall()
            assert not c.execute('SELECT * FROM magi_nodes WHERE job_id=%s',('b'*32,)).fetchall()
        assert store.restore('b'*32)=={}
    finally:
        ACTOR.reset(token); store.transaction=original


def test_public_gateway_login_gate_csrf_and_roles():
    class Client:
        def __init__(self,url):self.context={}
        def call(self,method,params=None):
            if method=='auth.info':return {'public':True,'login_available':False}
            if method=='auth.me':
                if self.context.get('session')!='fake-session-value':
                    from gateway.magi_client import MagiClientError
                    raise MagiClientError('로그인이 필요합니다.',status=401)
                return {'id':'u','role':'user','csrf':'fake-csrf'}
            return {'ok':True}
    app=create_app({'TESTING':True,'MAGI_PUBLIC_MODE':True,'MAGI_PUBLIC_ORIGIN':'https://magi.example','MAGI_CLIENT_FACTORY':Client})
    with app.test_client() as client:
        assert client.get('/api/jobs',base_url='https://magi.example').status_code==401
        client.set_cookie('__Host-magi_session','fake-session-value',domain='magi.example')
        assert client.get('/api/admin/overview',base_url='https://magi.example').status_code==403
        assert client.post('/api/jobs',json={'request':'test'},base_url='https://magi.example').status_code==403
        assert client.post('/api/jobs',json={'request':'test'},base_url='https://magi.example',headers={'Origin':'https://evil.example','X-CSRF-Token':'fake-csrf'}).status_code==403
        r=client.post('/api/jobs',json={'request':'test'},base_url='https://magi.example',headers={'Origin':'https://magi.example','X-CSRF-Token':'fake-csrf'})
        assert r.status_code==202 and r.headers['Cache-Control']=='no-store'
        assert r.headers['Content-Security-Policy']
        # TLS 종료 프록시의 내부 HTTP 연결에서도 외부 origin을 기준으로 검사한다.
        r=client.post('/api/jobs',json={'request':'test'},base_url='http://magi.example',headers={'Origin':'https://magi.example','X-CSRF-Token':'fake-csrf'})
        assert r.status_code==202


def test_google_requires_client_configuration():
    google=GoogleLogin('','','https://magi.example/auth/google/callback')
    assert not google.available
    with pytest.raises(AccessError):google.authorize('state','nonce','verifier')


def test_auth_info_does_not_misreport_backend_failure_as_oauth_configuration():
    from gateway.magi_client import MagiClientError
    class Client:
        def __init__(self,url):pass
        def call(self,*args):raise MagiClientError('작업 서버에 연결할 수 없습니다. 서버 상태를 확인하세요.')
    settings={'TESTING':True,'MAGI_PUBLIC_MODE':True,'MAGI_CLIENT_FACTORY':Client}
    app=create_app({**settings,'MAGI_PUBLIC_ORIGIN':'https://magi.example'})
    with app.test_client() as browser:
        response=browser.get('/api/auth/info',base_url='https://magi.example')
        assert response.status_code==503
        assert '작업 서버에 연결' in response.json['error']
        assert 'login_available' not in response.json
    app=create_app({**settings,'MAGI_PUBLIC_ORIGIN':''})
    with app.test_client() as browser:
        response=browser.get('/api/auth/info')
        assert response.status_code==503
        assert 'MAGI_PUBLIC_ORIGIN' in response.json['error']


def test_user_dto_preserves_question_forms_and_safe_document_links():
    from backend.access.service import user_payload
    value={'provider':'private','secret_debug':'private','state':{'question_forms':{'FOLLOWUP-1':{
        'question_id':'FOLLOWUP-1','question':'Choose','input_type':'single_choice','options':[{'id':'A','label':'A'}],
        'form_version':'version','private_debug':'private'}}},
        'job_id':'job','attrs':{'artifact_path':'final/FINAL_AGENT_SPEC.md','artifact_hash':'hash'}}
    public=user_payload(value)
    assert public['state']['question_forms']['FOLLOWUP-1']['options']==[{'id':'A','label':'A'}]
    assert public['job_id']=='job' and public['attrs']['artifact_hash']=='hash'
    assert 'private' not in json.dumps(public)
    assert 'artifact_path' not in user_payload({'attrs':{'artifact_path':'state/private_model_assignments.json'}})['attrs']


def test_public_rpc_auth_and_scoped_list(store,tmp_path):
    async def scenario():
        server=MagiServer(tmp_path,knowledge=KnowledgeService(store),public=lambda manager:PublicService(manager,pepper='fake-test-pepper'),internal_key='fake-internal-value')
        try:
            access=server.public.access
            sid,a=account(access,'a'); sid_b,b=account(access,'b')
            for uid,jid in [(a['id'],'a'*32),(b['id'],'b'*32)]:
                server.manager.jobs[jid]={'id':jid,'owner_id':uid,'request':'test','status':'FINALIZED','order':1,'provider':'openai','action':'approve'}
            result=json.loads(server._dispatch({'request_id':'r','method':'list','params':{},'session':sid}))
            assert [job['id'] for job in result['result']]==['a'*32]
            assert 'provider' not in result['result'][0]
            missing=json.loads(server._dispatch({'request_id':'r','method':'get','params':{'id':'b'*32},'session':sid}))
            assert missing['error']['code']=='not_found'
            assert json.loads(server._dispatch({'request_id':'r','method':'list','params':{}}))['error']['code']=='unauthorized'
        finally:server.manager.close()
    asyncio.run(scenario())


def test_atomic_admission_idempotency_worker_wait_and_resume(store,tmp_path,monkeypatch):
    monkeypatch.setenv('MAGI_SPEC_OPENAI_MODEL','gpt-6-luna')
    from backend.access.context import METER
    from backend.models import CompletionResult
    async def scenario():
        clock=[1800000000]
        prices={'gpt-6-luna':{'input_usd_per_million':'1','output_usd_per_million':'2','context_tokens':1000,'max_output_tokens':100,'context_limit_verified':True}}
        server=MagiServer(tmp_path,knowledge=KnowledgeService(store),public=lambda m:PublicService(m,prices=prices,pepper='fake-value',clock=lambda:clock[0]))
        server.manager.executor.submit=Mock()
        try:
            service=server.public; access=service.access
            sid,a=account(access,'a'); other,b=account(access,'b')
            def call(method,params,key='request-key-0001',user=a,session=sid):
                return json.loads(server._dispatch({'request_id':'r','method':method,'params':params,'idempotency_key':key,'session':session,'csrf':user['csrf']}))
            bad=call('generate',{'request':''})
            assert bad['error']['code']=='invalid'
            assert access.usage(a['id'])['runs']==0 and not access.status(a['id'])['busy']
            first=call('generate',{'request':'Create notes'})
            assert 'result' in first,first
            jid=first['result']['id']
            assert call('generate',{'request':'Create notes'})==first
            assert server.manager.executor.submit.call_count==1
            assert access.usage(a['id'])['runs']==1
            denied=call('generate',{'request':'Other'},user=b,session=other)
            assert denied['error']['code']=='busy' and access.usage(b['id'])['runs']==0
            def run(ident,action,payload):
                meter=METER.get()
                reservation=meter.reserve('gpt-6-luna')
                meter.settle(reservation,'gpt-6-luna',CompletionResult(text='Done',input_tokens=10,output_tokens=5))
                server.manager.jobs[ident]['status']='NEEDS_USER_INPUT'
            server.manager._run=run
            service.worker(jid,'generate',None)
            assert access.status(a['id'])['deadline']==clock[0]+180
            clock[0]+=180
            assert not access.status(a['id'])['busy']
            resumed=call('lease.resume',{'id':jid},key='request-key-0002')
            assert 'result' in resumed,resumed
            assert access.usage(a['id'])['runs']==1
            call('auth.logout',{})
            assert not access.status(b['id'])['busy']
        finally:server.manager.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('internal_key',['','fake-internal-key'])
def test_websocket_internal_auth_and_session_expiry(store,tmp_path,internal_key):
    from websockets.sync.client import connect
    # WASM 브리지는 단일 stdin/stdout을 사용한다. 실제 연결의 동시 트랜잭션을 흉내 내지 않는다.
    connect_bridge=store.connect
    bridge_lock=threading.RLock()
    class LockedConnection:
        def __init__(self,**kwargs):self.connection=connect_bridge(**kwargs)
        def __enter__(self):
            bridge_lock.acquire()
            try:return self.connection.__enter__()
            except BaseException:
                bridge_lock.release()
                raise
        def __exit__(self,*args):
            try:return self.connection.__exit__(*args)
            finally:bridge_lock.release()
    store.connect=LockedConnection
    async def scenario():
        server=MagiServer(tmp_path,knowledge=KnowledgeService(store),public=lambda m:PublicService(m,pepper='fake-value'),internal_key=internal_key)
        try:
            sid,a=account(server.public.access,'a')
            async with serve(server.handler,'127.0.0.1',0) as running:
                url=f'ws://127.0.0.1:{running.sockets[0].getsockname()[1]}'
                def forbidden():
                    with pytest.raises(Exception):
                        with connect(url,origin='https://magi.example') as socket:
                            socket.send(json.dumps({'request_id':'r','method':'list','params':{}}))
                            socket.recv(timeout=2)
                    client=MagiClient(url); client.internal_key=''
                    from gateway.magi_client import MagiClientError
                    with pytest.raises(MagiClientError):client.call('list')
                await asyncio.to_thread(forbidden)
                def subscribe():
                    client=MagiClient(url); client.internal_key=internal_key; client.context={'session':sid}
                    events=client.events(); assert next(events)=={'event':'ready'}
                    return events
                events=await asyncio.to_thread(subscribe)
                try:
                    server.manager.jobs['a'*32]={'owner_id':a['id']}
                    server.manager.jobs['b'*32]={'owner_id':'another-user'}
                    server._publish({'event':'job.changed','job':{'id':'b'*32}})
                    server._publish({'event':'job.changed','job':{'id':'a'*32}})
                    event=await asyncio.to_thread(next,events)
                    assert event['job']['id']=='a'*32
                    server.public.access.logout(sid)
                    from gateway.magi_client import MagiClientError
                    for _ in range(3):
                        try:buffered=await asyncio.to_thread(next,events)
                        except MagiClientError:break
                        assert buffered['event'] in {'service.status', 'keepalive'}
                    else:pytest.fail('폐기된 세션의 실시간 연결이 종료되지 않았습니다.')
                finally:await asyncio.to_thread(events.close)
        finally:server.manager.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('database_configured',[True,False])
def test_public_startup_does_not_require_internal_key(monkeypatch,database_configured):
    from unittest.mock import Mock,MagicMock,AsyncMock
    from backend.server import app as server_app
    from backend.server.diagnostics import diagnose_exception
    monkeypatch.setattr(server_app.os,'environ',{})
    monkeypatch.setattr('backend.knowledge.config.load_environment',lambda:None)
    monkeypatch.setattr('backend.knowledge.config.KnowledgeConfig.from_env',Mock(return_value=object() if database_configured else None))
    monkeypatch.setattr('backend.knowledge.store.KnowledgeStore',Mock())
    monkeypatch.setattr('backend.knowledge.runtime.KnowledgeService',Mock())
    runtime=Mock()
    monkeypatch.setattr('backend.access.runtime.PublicRuntime',Mock(return_value=runtime))
    server=Mock()
    factory=Mock(return_value=server)
    monkeypatch.setattr(server_app,'MagiServer',factory)
    listener=MagicMock()
    listener.__aenter__=AsyncMock(side_effect=asyncio.CancelledError)
    serve=Mock(return_value=listener)
    monkeypatch.setattr(server_app,'serve',serve)
    log=Mock()
    monkeypatch.setattr(server_app,'_log_exception',log)
    if database_configured:
        asyncio.run(server_app.main())
        assert factory.call_args.kwargs['internal_key']==''
        assert serve.call_args.args[1]=='127.0.0.1'
        assert serve.call_args.kwargs['origins']==[None]
        server.manager.close.assert_called_once()
        runtime.close.assert_called_once()
    else:
        with pytest.raises(SystemExit):asyncio.run(server_app.main())
        assert diagnose_exception(log.call_args.args[1])['reason']=='공개 모드에는 PostgreSQL 설정이 필요합니다.'
        factory.assert_not_called()


@pytest.mark.parametrize('superuser,bypass,locked,expected',[
    (True,False,True,'MAGI_DB_USER'),(False,True,True,'MAGI_DB_USER'),
    (False,False,False,'다른 공개 백엔드'),(False,False,True,None),
])
def test_public_runtime_role_and_process_diagnostics(superuser,bypass,locked,expected):
    from types import SimpleNamespace
    from unittest.mock import Mock,MagicMock
    from backend.access.runtime import PublicRuntime
    from backend.errors import InvalidStateError
    from backend.server.diagnostics import diagnose_exception
    connection=Mock()
    connection.execute.return_value.fetchone.side_effect=[{'rolsuper':superuser,'rolbypassrls':bypass},{'acquired':locked}]
    transaction=MagicMock()
    store=SimpleNamespace(connect=Mock(return_value=connection),config=SimpleNamespace(connection={}),transaction=Mock(return_value=transaction))
    runtime=PublicRuntime(store)
    if expected:
        with pytest.raises(InvalidStateError) as caught:runtime.acquire()
        assert expected in diagnose_exception(caught.value)['reason']
        connection.close.assert_called_once()
        transaction.__enter__.assert_not_called()
    else:
        runtime.acquire()
        connection.commit.assert_called_once()
        transaction.__enter__.assert_called_once()
        runtime.close()
        connection.close.assert_called_once()


def test_admin_boundary_revocation_and_saved_document_during_other_use(store,tmp_path):
    async def scenario():
        server=MagiServer(tmp_path,knowledge=KnowledgeService(store),public=lambda m:PublicService(m,pepper='fake-value'))
        try:
            access=server.public.access; sid,a=account(access,'a'); other,b=account(access,'b')
            jid='a'*32
            server.manager.jobs[jid]={'id':jid,'owner_id':a['id'],'request':'test','status':'FINALIZED','provider':'openai','action':'approve','order':1}
            server.manager.step=Mock(return_value={'id':'final','document':{'content':'# Saved document','filename':'FINAL_AGENT_SPEC.en.md','ref':'internal-history'}})
            with store.transaction() as c:access.acquire(c,b['id'],'other-job')
            def call(method,params=None):
                return json.loads(server._dispatch({'request_id':'r','method':method,'params':params or {},'session':sid,'csrf':a['csrf']}))
            doc=call('document',{'id':jid,'step_id':'final','language':'en'})
            assert doc['result']['content']=='# Saved document' and 'ref' not in doc['result']
            assert call('admin.overview')['error']['code']=='forbidden'
            assert call('cleanup.preview',{'scope':'all'})['error']['code']=='forbidden'
            assert call('knowledge.document',{'job_id':jid,'path':'state/magi_state.json'})['error']['code']=='not_found'
            with store.transaction() as c:c.execute("UPDATE magi_users SET role='admin' WHERE id=%s",(a['id'],))
            overview=call('admin.overview')
            assert 'result' in overview,overview
            assert overview['result']['daily_usd'] and 'subject_hash' not in overview['result']['users'][0]
            assert call('admin.user',{'id':b['id'],'role':'user','suspended':True,'daily_runs':3,'daily_usd':'2'})['result']['ok']
            with pytest.raises(AccessError):access.session(other)
        finally:server.manager.close()
    asyncio.run(scenario())


def test_admin_cleanup_preview_binding_and_admission_erasure(store,tmp_path):
    async def scenario():
        server=MagiServer(tmp_path,knowledge=KnowledgeService(store),public=lambda m:PublicService(m,pepper='fake-value'))
        try:
            access=server.public.access; sid,a=account(access,'a'); other,b=account(access,'b')
            jid='a'*32
            job={'id':jid,'owner_id':a['id'],'project_id':jid,'request':'private test input','status':'error','action':'generate','provider':'openai','demo':False,'order':1}
            store.create_project('test',jid); store.save_job(job)
            server.manager.jobs[jid]=job
            server.manager._export_job_locked(job)
            with store.transaction() as c:c.execute('INSERT INTO magi_admissions VALUES (%s,%s,%s,%s)',(a['id'],'key','fingerprint',store._json({'id':jid,'request':'private test input'})))
            def call(method,params,user=a,session=sid):
                return json.loads(server._dispatch({'request_id':'r','method':method,'params':params,'session':session,'csrf':user['csrf']}))
            assert call('cleanup.catalog',{})['error']['code']=='forbidden'
            assert call('cleanup.preview',{'scope':'jobs','ids':[jid]})['error']['code']=='forbidden'
            with store.transaction() as c:c.execute("UPDATE magi_users SET role='admin' WHERE id=%s",(a['id'],))
            preview=call('cleanup.preview',{'scope':'jobs','ids':[jid]})
            assert 'result' in preview,preview
            op=preview['result']['id']
            assert call('cleanup.execute',{'id':op},user=b,session=other)['error']['code']=='forbidden'
            deleted=call('cleanup.execute',{'id':op})
            assert deleted['result']['state']=='completed',deleted
            assert jid not in server.manager.jobs
            with store.transaction() as c:
                assert not c.execute('SELECT * FROM magi_admissions WHERE user_id=%s',(a['id'],)).fetchall()
                assert not c.execute('SELECT * FROM magi_jobs WHERE id=%s',(jid,)).fetchall()
            assert not access.status(a['id'])['busy']
        finally:server.manager.close()
    asyncio.run(scenario())
