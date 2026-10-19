"""관리자 HTML 접근 경계와 마지막 관리자 보호를 검증한다."""
from unittest.mock import Mock

import pytest

from backend.access.context import AccessError
from backend.access.service import PublicService
from gateway.app import create_app
from gateway.magi_client import MagiClientError
from test_public_service import access, account, store


def test_admin_cross_owner_knowledge_and_project_boundaries(store, tmp_path):
    import asyncio
    import json
    from backend.server.app import MagiServer
    from backend.knowledge.runtime import KnowledgeService

    async def scenario():
        server=MagiServer(tmp_path,knowledge=KnowledgeService(store),public=lambda manager:PublicService(manager,pepper='fake-pepper'))
        try:
            access=server.public.access
            sid,admin=account(access,'admin')
            other_sid,other=account(access,'other')
            with store.transaction() as c:
                c.execute("UPDATE magi_users SET role='admin' WHERE id=%s",(admin['id'],))
            projects=[]
            for index,owner in enumerate([admin['id'],other['id'],None],1):
                ident=str(index)*32
                store.create_project('project '+str(index),ident)
                store.commit_stage({'id':ident,'owner_id':owner,'project_id':ident,'request':'test'},'execution','spec_compile',
                                   {'user_request':'test'}, {'final/FINAL_AGENT_SPEC.md':'# Specification\n\n- A test requirement.'})
                projects.append(ident)
            store.create_project('empty','4'*32)
            original_transaction=store.transaction
            with store.transaction() as c:
                c.execute('CREATE ROLE magi_admin_test')
                c.execute('GRANT USAGE ON SCHEMA public TO magi_admin_test')
                c.execute('GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO magi_admin_test')
            from contextlib import contextmanager
            @contextmanager
            def restricted(**kwargs):
                with original_transaction(**kwargs) as c:
                    c.execute('SET LOCAL ROLE magi_admin_test')
                    yield c
            store.transaction=restricted
            def call(method,params=None,session=sid,actor=admin):
                return json.loads(server._dispatch({'request_id':'test','method':method,'params':params or {},'session':session,'csrf':actor['csrf']}))
            class ConnectedClient:
                def __init__(self,url): self.context={}
                def call(self,method,params=None):
                    response=json.loads(server._dispatch({'request_id':'gateway','method':method,'params':params or {},**self.context}))
                    if 'error' in response:
                        error=response['error']
                        raise MagiClientError(error['message'],status=401 if error['code']=='unauthorized' else 403)
                    return response['result']
            app=create_app({'TESTING':True,'MAGI_PUBLIC_MODE':True,'MAGI_PUBLIC_ORIGIN':'https://magi.example','MAGI_CLIENT_FACTORY':ConnectedClient})
            with app.test_client() as browser:
                browser.set_cookie('__Host-magi_session',sid,domain='magi.example')
                assert browser.get('/admin/knowledge',base_url='https://magi.example').status_code==200
                assert browser.get('/api/me',base_url='https://magi.example').status_code==200
                assert browser.get('/api/me',base_url='https://magi.example',headers={'X-CSRF-Token':''}).status_code==403
                assert browser.get('/api/admin/projects',base_url='https://magi.example',headers={'X-CSRF-Token':admin['csrf']}).status_code==200
                browser.set_cookie('__Host-magi_session',other_sid,domain='magi.example')
                for path in ['/api/admin/projects','/api/admin/graph?project_id='+projects[0],'/api/cleanup/catalog']:
                    assert browser.get(path,base_url='https://magi.example').status_code==403
            assert len(call('admin.projects')['result'])==4
            assert call('admin.projects',session=other_sid,actor=other)['error']['code']=='forbidden'
            for project in projects:
                graph=call('admin.graph',{'project_id':project,'depth':0,'limit':100})
                assert 'result' in graph,graph
                assert graph['result']['nodes']
                node=graph['result']['nodes'][0]['id']
                detail=call('admin.node',{'project_id':project,'node_id':node})
                assert detail['result']['project_id']==project
                wrong=next(ident for ident in projects if ident!=project)
                assert 'error' in call('admin.node',{'project_id':wrong,'node_id':node})
                assert 'error' in call('admin.graph',{'project_id':wrong,'job_id':project})
                assert 'error' in call('admin.document',{'project_id':wrong,'job_id':project,'path':'final/FINAL_AGENT_SPEC.md'})
                assert 'error' in call('admin.document',{'project_id':project,'job_id':project,'path':'state/magi_state.json'})
                assert call('admin.jobs',{'project_id':project})['result'][0]['id']==project
                assert 'result' in call('admin.search',{'project_id':project,'query':'test'})
                with original_transaction() as c:
                    artifact=c.execute('SELECT content_hash FROM magi_artifacts WHERE job_id=%s AND path=%s',(project,'final/FINAL_AGENT_SPEC.md')).fetchone()
                assert 'result' in call('admin.document',{'project_id':project,'job_id':project,'path':'final/FINAL_AGENT_SPEC.md','content_hash':artifact['content_hash']})
            assert call('admin.graph',{'project_id':'4'*32})['result']['nodes']==[]
            assert 'error' in call('admin.graph',{})
            # 일반 사용자 그래프에는 다른 사용자와 소유자 없는 작업이 나타나지 않는다.
            graph=call('knowledge.graph',{'depth':0},session=other_sid,actor=other)['result']
            assert {node['project_id'] for node in graph['nodes']}=={projects[1]}
            assert call('cleanup.execute',{'id':'unknown'},session=other_sid,actor=other)['error']['code']=='forbidden'
            assert __import__('backend.access.context',fromlist=['ACTOR']).ACTOR.get() is None
        finally:
            server.manager.close()
    asyncio.run(scenario())


class AdminClient:
    def __init__(self, url):
        self.context = {}

    def call(self, method, params=None):
        session = self.context.get('session')
        if session not in {'admin', 'user'}:
            raise MagiClientError('로그인이 필요합니다.', status=401)
        return {'id': 'test-user', 'role': session, 'csrf': 'test-csrf'}


def test_admin_browser_desktop_and_mobile():
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which('node')
    packages = Path(node).parent.parent / 'node_modules' if node else Path('/missing')
    if not (packages / 'playwright').is_dir():
        pytest.skip('Playwright runtime unavailable')
    app = create_app({'TESTING': True, 'MAGI_PUBLIC_MODE': True,
                      'MAGI_PUBLIC_ORIGIN': 'https://magi.example', 'MAGI_CLIENT_FACTORY': AdminClient})
    with app.test_request_context(base_url='https://magi.example'):
        from flask import render_template
        html = render_template('admin.html', login_required=False)
    result = subprocess.run([node, str(Path(__file__).with_name('admin_ui.mjs')), str(packages),
                             str(Path.cwd()), html], capture_output=True, text=True, encoding='utf-8',
                            timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert result.returncode == 0, result.stderr


def test_admin_html_requires_admin_session():
    app = create_app({'TESTING': True, 'MAGI_PUBLIC_MODE': True,
                      'MAGI_PUBLIC_ORIGIN': 'https://magi.example', 'MAGI_CLIENT_FACTORY': AdminClient})
    with app.test_client() as client:
        response = client.get('/admin', base_url='https://magi.example')
        assert response.status_code == 401
        assert 'Google로 로그인' in response.text and 'admin.js' not in response.text
        for role, status in [('user', 403), ('admin', 200)]:
            client.set_cookie('__Host-magi_session', role, domain='magi.example')
            response = client.get('/admin', base_url='https://magi.example')
            assert response.status_code == status
        assert 'admin.js' in response.text
        assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('role,suspended', [('user', False), ('admin', True)])
def test_last_active_admin_cannot_be_removed(access, role, suspended):
    sid, user = account(access, 'owner')
    with access.store.transaction() as c:
        c.execute("UPDATE magi_users SET role='admin' WHERE id=%s", (user['id'],))
    manager = Mock()
    manager.lock = __import__('threading').RLock()
    manager.knowledge.store = access.store
    service = PublicService(manager)
    payload = dict(id=user['id'], role=role, suspended=suspended, daily_runs=10, daily_usd='1')
    with pytest.raises(AccessError, match='마지막 활성 관리자'):
        service.admin(access.session(sid), 'admin.user', payload)
    assert access.session(sid)['role'] == 'admin'
    _, other = account(access, 'second-admin')
    with access.store.transaction() as c:
        c.execute("UPDATE magi_users SET role='admin' WHERE id=%s", (other['id'],))
    service.admin(access.session(sid), 'admin.user', payload)
    with pytest.raises(AccessError):
        access.session(sid)

