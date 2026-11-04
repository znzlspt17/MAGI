import pytest
from flask import Flask

from gateway.public import install


@pytest.mark.parametrize("origin", ["", "https://magi.example"])
def test_research_is_public_without_session_or_backend(origin, monkeypatch):
    app = Flask(__name__)
    app.config.update(PUBLIC_MODE=True, PUBLIC_ORIGIN=origin, LOCAL_LOGIN=False, PROXY_HOPS=0)

    def forbidden_client():
        pytest.fail("공개 연구 안내는 인증이나 백엔드 연결이 필요하지 않습니다.")

    monkeypatch.setattr("gateway.public.render_frontend", lambda: "<main>research frontend</main>")
    install(app, forbidden_client)
    response = app.test_client().get("/research", base_url=origin or "http://localhost")
    assert response.status_code == 200
    assert b"research frontend" in response.data
    assert "Set-Cookie" not in response.headers
