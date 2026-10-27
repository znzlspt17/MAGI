"""실제 React 화면을 검증한다. 로그 저장소·인증 응답은 브라우저 모형이다."""
from browser_runtime import gateway_server, run_browser
from gateway.app import create_app
from gateway.frontend import render_frontend


def test_admin_logs_browser():
    app = create_app({"PUBLIC_MODE": False, "TESTING": True})
    # 브라우저에서는 모형 관리자 API를 사용하며 서버 권한은 test_logs에서 별도 검증한다.
    app.view_functions["admin_page"] = lambda **_: render_frontend()
    with gateway_server(app) as url:
        assert "pagination passed" in run_browser("admin_logs_ui.mjs", url)


def test_admin_job_validation_browser():
    app = create_app({"PUBLIC_MODE": False, "TESTING": True})
    app.view_functions["admin_page"] = lambda **_: render_frontend()
    with gateway_server(app) as url:
        assert "log filters passed" in run_browser("job_validation_ui.mjs", url)
