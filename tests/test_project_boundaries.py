"""분리된 구성 요소의 의존 경계와 실제 통신을 검증한다."""

import asyncio

from websockets.asyncio.server import serve

from backend.infrastructure.prompts import load_prompt
from backend.server.app import MagiServer
from gateway.app import create_app
from gateway.magi_client import MagiClient


def test_frontend_and_prompts_are_available(monkeypatch, tmp_path):
    # 실행 위치가 프로젝트 밖이어도 설치된 리소스를 찾을 수 있어야 한다.
    monkeypatch.chdir(tmp_path)
    app = create_app({"MAGI_PUBLIC_MODE": False, "TESTING": True})
    with app.test_client() as client:
        response = client.get("/")
        assert response.status_code == 200
        assert 'MAGI 작업 공간' in response.text
        for name in ("app.js", "styles.css", "tailwind.css", "ui.css", "admin.css"):
            assert client.get(f"/static/{name}").status_code == 200
    assert load_prompt("compiler")


def test_gateway_to_backend_and_events(tmp_path):
    async def scenario():
        server = MagiServer(tmp_path)
        try:
            async with serve(server.handler, "127.0.0.1", 0) as socket_server:
                port = socket_server.sockets[0].getsockname()[1]
                url = f"ws://127.0.0.1:{port}"

                def request():
                    app = create_app({"MAGI_PUBLIC_MODE": False, "TESTING": True, "MAGI_SERVER_URL": url})
                    with app.test_client() as client:
                        response = client.get("/api/jobs")
                        assert response.status_code == 200
                        assert response.json == []
                        assert client.get("/api/jobs/missing").status_code == 404
                        assert client.get('/api/cleanup/catalog').status_code == 403
                        assert client.post('/api/cleanup/preview',json={'scope':'all'}).status_code == 403
                        assert client.post('/api/cleanup/execute',json={'id':'f'*32}).status_code == 403
                        direct=MagiClient(url)
                        from gateway.magi_client import MagiClientError
                        import pytest
                        with pytest.raises(MagiClientError): direct.call('cleanup.catalog')


                await asyncio.to_thread(request)
                events = MagiClient(url).events()
                try:
                    assert await asyncio.to_thread(next, events) == {"event": "ready"}
                    server._publish({"event": "job.changed", "id": "fixture"})
                    event = await asyncio.to_thread(next, events)
                    assert event == {"event": "job.changed", "id": "fixture"}
                finally:
                    await asyncio.to_thread(events.close)
        finally:
            server.manager.close()

    asyncio.run(scenario())
