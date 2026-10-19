"""Google 로그인 결과를 검증하고 계정 구분용 식별자만 전달한다."""

from backend.access.context import AccessError


class GoogleLogin:
    def __init__(self, client_id, client_secret, redirect_uri, *, local_login=False):
        self.client_id, self.client_secret, self.redirect_uri = client_id, client_secret, redirect_uri
        self.local_login = local_login

    @property
    def available(self):
        from protocol.web_config import login_origin
        from urllib.parse import urlsplit
        parsed=urlsplit(self.redirect_uri)
        try:
            login_origin(f'{parsed.scheme}://{parsed.netloc}',self.local_login)
        except ValueError:
            return False
        return bool(self.client_id and self.client_secret and parsed.path=='/auth/google/callback' and not parsed.query and not parsed.fragment)

    def _client(self, **kwargs):
        if not self.available:
            raise AccessError('Google OAuth 클라이언트 설정을 확인하세요.', 'unavailable')
        from authlib.integrations.requests_client import OAuth2Session
        return OAuth2Session(self.client_id, self.client_secret, scope='openid',
                             redirect_uri=self.redirect_uri, code_challenge_method='S256', **kwargs)

    def authorize(self, state, nonce, verifier):
        with self._client(state=state) as client:
            url, _ = client.create_authorization_url('https://accounts.google.com/o/oauth2/v2/auth',
                    state=state, nonce=nonce, code_verifier=verifier, include_granted_scopes='false', access_type='online')
            return url

    def subject(self, code, nonce, verifier):
        from authlib.jose import JsonWebToken
        from authlib.oidc.core import CodeIDToken
        import requests
        try:
            with self._client() as client:
                response = client.fetch_token('https://oauth2.googleapis.com/token', code=code,
                                              code_verifier=verifier, timeout=10)
            keys = requests.get('https://www.googleapis.com/oauth2/v3/certs', timeout=10)
            keys.raise_for_status()
            claims = JsonWebToken(['RS256']).decode(response['id_token'], keys.json(), claims_cls=CodeIDToken,
                claims_options={'iss': {'essential': True, 'values': ['https://accounts.google.com', 'accounts.google.com']},
                                'aud': {'essential': True, 'value': self.client_id}, 'exp': {'essential': True}},
                claims_params={'nonce': nonce, 'client_id': self.client_id, 'access_token': response.get('access_token')})
            claims.validate(leeway=30)
            if claims.get('nonce') != nonce or claims.get('azp', self.client_id) != self.client_id:
                raise ValueError()
            subject=claims.get('sub')
            if not isinstance(subject,str) or not 1 <= len(subject) <= 255:
                raise ValueError()
            return subject
        except AccessError:
            raise
        except Exception:
            raise AccessError('Google 로그인 결과를 확인할 수 없습니다.', 'unauthorized') from None
