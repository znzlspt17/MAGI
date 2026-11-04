"""브라우저용 서버 세션·CSRF·운영 API 경계."""
from typing import Any

import secrets
import hashlib
import threading
import time
from urllib.parse import urlsplit
from flask import abort, g, jsonify, redirect, request
from gateway.client import ClientError
from protocol.web_config import login_origin
from ipaddress import ip_address
from gateway.frontend import render_frontend

COOKIE='__Host-session'
LOGIN_COOKIE='__Host-login'


def install(app, client):
    public=app.config['PUBLIC_MODE']
    origin=app.config['PUBLIC_ORIGIN']
    local_login=app.config['LOCAL_LOGIN']
    secure=not local_login
    cookie='local_session' if local_login else COOKIE
    login_cookie='local_login' if local_login else LOGIN_COOKIE
    app.config['SESSION_COOKIE']=cookie
    windows: dict[str, tuple[int, int]]={}
    rate_lock=threading.Lock()
    salt=secrets.token_bytes(32)
    if public and (origin or local_login):
        origin=login_origin(origin,local_login)
        app.config['PUBLIC_ORIGIN']=origin
        parsed=urlsplit(origin)
        app.config['TRUSTED_HOSTS']=[parsed.hostname]
        if local_login:
            app.config['TRUSTED_HOSTS']=['localhost','127.0.0.1','[::1]']
    if local_login and app.config['PROXY_HOPS']:
        raise ValueError('로컬 로그인은 프록시 없이 loopback에서만 사용하세요.')

    @app.before_request
    def boundary():
        g.request_id=secrets.token_hex(12)
        g.log_started=time.monotonic()
        from protocol.logging import log_context
        g.log_context = log_context(trace_id=g.request_id)
        g.log_context.__enter__()
        if not public:
            if request.path.startswith(('/api/admin/','/api/cleanup/')):
                abort(403)
            return None
        if local_login and (not request.remote_addr or not ip_address(request.remote_addr).is_loopback):
            abort(403)
        if local_login and request.host != urlsplit(origin).netloc:
            # 로그인 쿠키와 OAuth 콜백이 같은 localhost 주소를 사용하게 한다.
            path=request.full_path.rstrip('?') if not request.query_string else request.full_path
            return redirect(origin+path,code=307)
        if request.path.startswith(('/api/','/auth/','/ws/')):
            minute=int(time.monotonic()//60)
            identity=hashlib.sha256(salt+(request.remote_addr or '').encode()).hexdigest()
            with rate_lock:
                for key in [key for key,value in windows.items() if value[0]<minute]:
                    del windows[key]
                old=windows.get(identity,(minute,0))
                if (identity not in windows and len(windows)>=4096) or old[1]>=240:
                    return jsonify(error='요청이 너무 많습니다. 잠시 후 다시 시도하세요.',request_id=g.request_id),429
                windows[identity]=(minute,old[1]+1)
        if not origin:
            if request.path not in {'/','/privacy','/licenses','/research','/api/auth/info'} and not request.path.startswith('/static/'):
                return jsonify(error='공개 서비스 설정이 필요합니다.',request_id=g.request_id),503
        if request.path in {'/','/privacy','/licenses','/research','/api/auth/info','/auth/google/start','/auth/google/callback'} or request.path.startswith('/static/'):
            return None
        if request.path.startswith(('/api/','/ws/')):
            try:
                g.actor=client().call('auth.me')
            except ClientError as exc:
                return jsonify(error=str(exc),request_id=g.request_id),exc.status
            if request.path.startswith(('/api/admin/','/api/cleanup/')) and g.actor['role']!='admin':
                abort(403)
            if request.path.startswith('/ws/'):
                if request.headers.get('Origin')!=origin:
                    abort(403)
            if request.method not in {'GET','HEAD','OPTIONS'}:
                if request.headers.get('Origin')!=origin or request.headers.get('Sec-Fetch-Site')=='cross-site':
                    abort(403)
                if not secrets.compare_digest(request.headers.get('X-CSRF-Token',''),g.actor['csrf']):
                    abort(403)

    @app.teardown_request
    def clear_log_context(_error):
        context = g.pop("log_context", None)
        if context is not None:
            context.__exit__(None, None, None)

    @app.after_request
    def response_headers(response):
        from protocol.logging import get_logger
        if not request.path.startswith(('/static/', '/health')):
            get_logger(__name__).info("http_completed", request_id=getattr(g, 'request_id', ''),
                                      method=request.method, status=response.status_code,
                                      duration_ms=round((time.monotonic()-getattr(g, 'log_started', time.monotonic()))*1000, 2))
        response.headers['X-Request-ID']=getattr(g,'request_id','')
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if public:
            response.headers['Cache-Control']='no-store' if not request.path.startswith('/static/') else 'no-cache'
            if secure:
                response.headers['Strict-Transport-Security']='max-age=31536000'
        return response

    @app.get('/api/auth/info')
    def auth_info():
        if not public:
            return jsonify(public=False,login_available=False)
        if not origin:
            return jsonify(error='게이트웨이에 PUBLIC_ORIGIN(공개 HTTPS 주소)이 설정되지 않았습니다.',request_id=g.request_id),503
        try:
            return jsonify(client().call('auth.info'))
        except ClientError as exc:
            return jsonify(error=str(exc),request_id=g.request_id),exc.status

    @app.get('/auth/google/start')
    def google_start():
        if not public:
            abort(404)
        try:
            payload=client().call('auth.start')
            response=redirect(payload['url'])
            response.set_cookie(login_cookie,payload['browser'],max_age=300,secure=secure,httponly=True,samesite='Lax',path='/')
            return response
        except ClientError as exc:
            return jsonify(error=str(exc),request_id=g.request_id),exc.status

    @app.get('/auth/google/callback')
    def google_callback():
        if not public:
            abort(404)
        try:
            payload=client().call('auth.callback',{'state':request.args.get('state'),'code':request.args.get('code'),
                                                  'browser':request.cookies.get(login_cookie)})
            response=redirect('/')
            response.set_cookie(cookie,payload['session'],max_age=86400,secure=secure,httponly=True,samesite='Lax',path='/')
        except ClientError as exc:
            response=jsonify(error=str(exc),request_id=g.request_id)
            response.status_code=exc.status
        response.delete_cookie(login_cookie,secure=secure,httponly=True,samesite='Lax',path='/')
        return response

    def relay(method,params=None):
        try:
            return jsonify(client().call(method,params or {}))
        except ClientError as exc:
            return jsonify(error=str(exc),request_id=g.request_id),exc.status

    @app.get('/admin')
    @app.get('/admin/<section>')
    def admin_page(section='overview'):
        if section not in {'overview','users','data','knowledge','costs','logs'}:
            abort(404)
        if not public:
            abort(404)
        try:
            actor=client().call('auth.me')
        except ClientError as exc:
            if exc.status==401:
                page = app.make_response(render_frontend())
                page.status_code = 401
                return page
            return '관리자 인증 상태를 확인할 수 없습니다. 잠시 후 다시 시도하세요.',exc.status
        if actor['role']!='admin':
            abort(403)
        return render_frontend()

    @app.get('/api/me')
    def me():
        return relay('auth.me')

    @app.get('/api/me/usage')
    def usage():
        return relay('usage')

    @app.get('/settings/mcp')
    def mcp_settings_page():
        if not public:
            abort(404)
        try:
            client().call('auth.me')
        except ClientError as exc:
            if exc.status == 401:
                page = app.make_response(render_frontend())
                page.status_code = 401
                return page
            return '인증 상태를 확인할 수 없습니다.', exc.status
        return render_frontend()

    @app.get('/oauth/mcp-client-metadata.json')
    def mcp_oauth_client_metadata():
        if not public or not origin or not origin.startswith('https://'):
            abort(404)
        return jsonify(client_id=origin + '/oauth/mcp-client-metadata.json', client_name='MAGI',
                       redirect_uris=[origin + '/auth/mcp/callback'], grant_types=['authorization_code', 'refresh_token'],
                       response_types=['code'], token_endpoint_auth_method='none')

    @app.route('/api/mcp/connections', methods=['GET', 'POST'])
    def mcp_connections():
        if not public:
            abort(404)
        return relay('mcp.list' if request.method == 'GET' else 'mcp.create',
                     {} if request.method == 'GET' else request.get_json(silent=True) or {})

    @app.route('/api/mcp/connections/<ident>', methods=['GET', 'PATCH', 'DELETE'])
    def mcp_connection(ident):
        if not public:
            abort(404)
        method = {'GET': 'mcp.get', 'PATCH': 'mcp.update', 'DELETE': 'mcp.delete'}[request.method]
        data = request.get_json(silent=True) or {} if request.method == 'PATCH' else {}
        if not isinstance(data, dict):
            abort(400)
        return relay(method, {**data, 'id': ident})

    @app.post('/api/mcp/connections/<ident>/test')
    def mcp_test(ident):
        if not public:
            abort(404)
        return relay('mcp.test', {'id': ident})

    @app.post('/api/mcp/connections/<ident>/oauth/start')
    def mcp_oauth_start(ident):
        if not public:
            abort(404)
        return relay('mcp.oauth.start', {'id': ident, 'origin': origin})

    @app.get('/auth/mcp/callback')
    def mcp_oauth_callback():
        if not public:
            abort(404)
        try:
            client().call('mcp.oauth.callback', {'state': request.args.get('state'),
                'code': request.args.get('code'), 'origin': origin})
            response = redirect('/settings/mcp')
        except ClientError:
            response = redirect('/settings/mcp?oauth=failed')
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.get('/api/service/status')
    def status():
        return relay('service.status')

    @app.post('/api/logout')
    def logout():
        response=app.make_response(relay('auth.logout'))
        if response.status_code==200:
            response.delete_cookie(cookie,secure=secure,httponly=True,samesite='Lax',path='/')
        return response

    @app.get('/api/admin/logs')
    @app.get('/api/admin/logs/status')
    def admin_logs():
        from gateway.logs import LogStore, LogError
        store = LogStore(app.config['LOG_STORE_URL'])
        try:
            data = store.status() if request.path.endswith('/status') else store.search(request.args)
            response = jsonify(data)
        except LogError as exc:
            response = jsonify(error=str(exc), code=exc.code, request_id=g.request_id)
            response.status_code = exc.status
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route('/api/admin/<action>',methods=['GET','POST'])
    def admin(action):
        allowed={'overview','job','user_jobs','usage','projects','jobs','graph','search','node','document'} if request.method=='GET' else {'user','claim','stop','settle','settings'}
        if action not in allowed:
            abort(404)
        params: dict[str, Any]=dict(request.args) if request.method=='GET' else request.get_json(silent=True) or {}
        for key in ('depth','limit','offset'):
            if key in params:
                try: params[key]=int(params[key])
                except (ValueError,TypeError): abort(400)
        return relay('admin.'+action,params)

    @app.get('/api/admin/usage/rows')
    def admin_usage_rows():
        params: dict[str, Any]=dict(request.args)
        for key in ('limit','offset'):
            if key in params:
                try: params[key]=int(params[key])
                except (ValueError,TypeError): abort(400)
        return relay('admin.usage.rows',params)

    @app.get('/api/admin/job/validation')
    def admin_job_validation():
        if any(len(request.args.getlist(key)) != 1 for key in request.args):
            abort(400)
        return relay('admin.job.validation', dict(request.args))

    @app.route('/api/admin/cleanup/<action>',methods=['GET','POST'])
    def admin_cleanup(action):
        if action not in ({'catalog'} if request.method=='GET' else {'preview','execute'}):
            abort(404)
        return relay('cleanup.'+action,request.get_json(silent=True) or {})

    @app.get('/research')
    def research():
        return render_frontend()

    @app.get('/licenses')
    def licenses():
        return render_frontend()

    @app.get('/privacy')
    def privacy():
        return render_frontend()
