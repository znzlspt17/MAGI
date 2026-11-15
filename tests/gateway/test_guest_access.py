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
    assert '__Host-session=' in cookie and 'Secure' in cookie and 'HttpOnly' in cookie
    assert 'Max-Age=2592000' in cookie and 'SameSite=Lax' in cookie


def test_guest_bootstrap_rejects_cross_site_before_rpc():
    rpc = FakeClient()
    response = _app(rpc).test_client().post('/api/auth/guest', base_url='https://magi.example',
                                         headers={'Origin': 'https://evil.example', 'Sec-Fetch-Site': 'cross-site'})
    assert response.status_code == 403
    assert rpc.calls == []
