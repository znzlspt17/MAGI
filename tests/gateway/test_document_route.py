"""문서 조회 경로는 언어 선택 없이 한국어 원본 요청을 전달한다."""

from gateway.app import create_app


def test_document_route_forwards_empty_body_without_language():
    calls = []
    class FakeClient:
        def __init__(self, _url):
            pass

        def call(self, method, params):
            calls.append((method, params))
            return {"content": "저장된 명세입니다.", "language": "ko", "filename": "SPEC.ko.md"}

    app = create_app({"TESTING": True, "PUBLIC_MODE": False, "CLIENT_FACTORY": FakeClient})
    response = app.test_client().post("/api/jobs/job/steps/step/document", json={})
    assert response.status_code == 200
    assert response.get_json()["content"] == "저장된 명세입니다."
    assert response.get_json()["language"] == "ko"
    assert response.headers["Cache-Control"] == "no-store"
    assert calls == [("document", {"id": "job", "step_id": "step"})]
