from flask import Flask

from gateway.public import install


class FakeClient:
    def __init__(self):
        self.calls = []

    def call(self, method, params=None):
        self.calls.append((method, params))
        if method == 'auth.guest':
            return {'session': 'fake-guest-session-id', 'max_age': 2592000}
        raise AssertionError(method)


def _app(client):
    app = Flask(__name__)
    app.config.update(PUBLIC_MODE=True, PUBLIC_ORIGIN='https://magi.example', LOCAL_LOGIN=False, PROXY_HOPS=0)
    install(app, lambda: client)
    return app


def test_guest_bootstrap_issues_secure_cookie_from_same_origin():
    rpc = FakeClient()
    response = _app(rpc).test_client().post('/api/auth/guest', base_url='https://magi.example',
                                         headers={'Origin': 'https://magi.example'})
    assert response.status_code == 200
    assert rpc.calls == [('auth.guest', None)]
    cookie = response.headers['Set-Cookie']
    assert '__Host-guest-session=' in cookie and 'Secure' in cookie and 'HttpOnly' in cookie
    assert 'Max-Age=2592000' in cookie and 'SameSite=Lax' in cookie


def test_guest_bootstrap_rejects_cross_site_before_rpc():
    rpc = FakeClient()
    response = _app(rpc).test_client().post('/api/auth/guest', base_url='https://magi.example',
                                         headers={'Origin': 'https://evil.example', 'Sec-Fetch-Site': 'cross-site'})
    assert response.status_code == 403
    assert rpc.calls == []


def test_guest_response_does_not_replace_google_cookie():
    rpc = FakeClient()
    client = _app(rpc).test_client()
    client.set_cookie('__Host-session', 'google-session', domain='magi.example')
    response = client.post('/api/auth/guest', base_url='https://magi.example',
                           headers={'Origin': 'https://magi.example'})
    assert response.status_code == 200
    assert client.get_cookie('__Host-session', domain='magi.example').value == 'google-session'
    assert client.get_cookie('__Host-guest-session', domain='magi.example').value == 'fake-guest-session-id'


def test_late_guest_response_after_google_callback_keeps_both_cookies():
    from http.cookies import SimpleCookie
    class LoginClient(FakeClient):
        def call(self, method, params=None):
            if method == 'auth.callback': return {'session': 'google-session-value'}
            return super().call(method, params)
    app = _app(LoginClient())
    first = app.test_client()
    delayed = first.post('/api/auth/guest', base_url='https://magi.example',
                         headers={'Origin': 'https://magi.example'})
    cookie = SimpleCookie()
    cookie.load(delayed.headers['Set-Cookie'])
    browser = app.test_client()
    response = browser.get('/auth/google/callback?state=s&code=c', base_url='https://magi.example')
    assert response.status_code == 302
    for name, morsel in cookie.items():
        browser.set_cookie(name, morsel.value, domain='magi.example')
    assert browser.get_cookie('__Host-session', domain='magi.example').value == 'google-session-value'
    assert browser.get_cookie('__Host-guest-session', domain='magi.example').value == 'fake-guest-session-id'


def test_gateway_forwards_both_cookies_to_authenticated_rpc():
    from gateway.app import create_app
    calls = []
    class Client:
        def __init__(self, _url): self.context = {}
        def call(self, method, params=None):
            calls.append((method, dict(self.context)))
            return {'id': 'account', 'role': 'user', 'csrf': 'fake-csrf'}
    app = create_app({'TESTING': True, 'PUBLIC_MODE': True, 'PUBLIC_ORIGIN': 'https://magi.example',
                      'LOCAL_LOGIN': False, 'PROXY_HOPS': 0, 'CLIENT_FACTORY': Client})
    browser = app.test_client()
    browser.set_cookie('__Host-session', 'google-session', domain='magi.example')
    browser.set_cookie('__Host-guest-session', 'guest-session', domain='magi.example')
    assert browser.get('/api/me', base_url='https://magi.example').status_code == 200
    assert all(context['session'] == 'google-session' and context['guest_session'] == 'guest-session'
               for method, context in calls if method == 'auth.me')
