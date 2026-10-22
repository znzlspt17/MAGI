"""Loopback Flask compatibility API and browser event relay."""

from __future__ import annotations

import base64
import io
import json
import os
from importlib.resources import files

from flask import Flask, abort, jsonify, request, send_file, g, current_app
from flask_sock import Sock
from werkzeug.exceptions import HTTPException

from gateway.client import Client, ClientError
from protocol.diagnostics import traceback_frames


def create_app(config: dict | None = None) -> Flask:
    from protocol.deployment import validate_container
    validate_container('gateway')
    frontend = files("frontend")
    app = Flask(
        __name__,
        template_folder=str(frontend.joinpath("templates")),
        static_folder=str(frontend.joinpath("static")),
    )
    app.config.update(
        SERVER_URL=os.environ.get("SERVER_URL", "ws://127.0.0.1:8765"),
        CLIENT_FACTORY=Client,
        MAX_CONTENT_LENGTH=128 * 1024,
        TRUSTED_HOSTS=["localhost", "127.0.0.1", "[::1]"],
        SOCK_SERVER_OPTIONS={"max_message_size": 128 * 1024, "ping_interval": 25},
        PUBLIC_MODE=os.environ.get('PUBLIC_MODE','1')!='0',
        PUBLIC_ORIGIN=os.environ.get('PUBLIC_ORIGIN',''),
        LOCAL_LOGIN=os.environ.get('LOCAL_LOGIN','0')=='1',
        PROXY_HOPS=int(os.environ.get('PROXY_HOPS','0')),
    )
    if config:
        app.config.update(config)
    hops=app.config['PROXY_HOPS']
    if type(hops) is not int or not 0<=hops<=2:
        raise ValueError('신뢰할 프록시 수가 올바르지 않습니다.')
    if hops:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app=ProxyFix(app.wsgi_app,x_for=hops,x_proto=hops,x_host=0)
    sock = Sock(app)

    def client() -> Client:
        instance=app.config["CLIENT_FACTORY"](app.config["SERVER_URL"])
        if app.config['PUBLIC_MODE']:
            instance.context={key:value for key,value in {
                'session':request.cookies.get(app.config['SESSION_COOKIE']),'csrf':request.headers.get('X-CSRF-Token'),
                'idempotency_key':request.headers.get('Idempotency-Key')}.items() if value is not None}
        return instance

    from gateway.public import install
    install(app,client)

    from gateway.health import install_health
    install_health(app, client)

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith("/api/"):
            return jsonify(error="요청을 처리할 수 없습니다.",request_id=getattr(g,'request_id','')), error.code
        return error

    @app.errorhandler(Exception)
    def unexpected_error(error):
        app.logger.error(
            "unexpected request failure request_id=%s method=%s route=%s exception_type=%s frames=%s",
            getattr(g, 'request_id', ''), request.method,
            request.url_rule.rule if request.url_rule else 'unmatched',
            type(error).__name__, traceback_frames(error),
        )
        if request.path.startswith("/api/"):
            return jsonify(error="요청을 처리하지 못했습니다.",request_id=getattr(g,'request_id','')), 500
        return "요청을 처리하지 못했습니다.", 500

    @app.get("/")
    def index():
        from gateway.frontend import render_frontend
        return render_frontend()

    @app.get('/jobs/<ident>')
    def workspace_job(ident):
        from gateway.frontend import render_frontend
        return render_frontend()

    @app.get("/api/jobs")
    def jobs():
        try:
            response = jsonify(client().call("list"))
        except ClientError as exc:
            return _client_error(exc)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/cleanup/catalog")
    def cleanup_catalog():
        try:
            response = jsonify(client().call("cleanup.catalog", {}))
            response.headers["Cache-Control"] = "no-store"
            return response
        except ClientError as exc:
            return _client_error(exc)

    @app.post("/api/cleanup/<action>")
    def cleanup_action(action):
        if action not in {"preview", "execute"}:
            abort(404)
        try:
            response = jsonify(client().call("cleanup." + action, _json()))
            response.headers["Cache-Control"] = "no-store"
            return response
        except ClientError as exc:
            return _client_error(exc, mutation=action == "execute")

    @app.get("/api/jobs/<ident>")
    def job(ident):
        try:
            response = jsonify(client().call("get", {"id": ident}))
        except ClientError as exc:
            return _client_error(exc)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/jobs/<ident>/steps/<step_id>")
    def job_step(ident, step_id):
        """Relay a single saved execution-step detail without exposing storage paths."""
        try:
            response = jsonify(client().call("get", {"id": ident, "step_id": step_id}))
        except ClientError as exc:
            return _client_error(exc)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/jobs/<ident>/steps/<step_id>/document")
    def job_document(ident, step_id):
        data = _json()
        language = data.get("language")
        if not isinstance(language, str) or language not in {"ko", "en"}:
            return jsonify(error="문서 언어는 한국어 또는 영어를 선택하세요."), 400
        try:
            response = jsonify(client().call("document", {"id": ident, "step_id": step_id, "language": language}))
            response.headers["Cache-Control"] = "no-store"
            return response
        except ClientError as exc:
            return _client_error(exc)

    @app.post("/api/jobs")
    def create():
        data = _json()
        request_text = data.get("request")
        demo = data.get("demo")
        provider = data.get("provider")
        if (
            not isinstance(request_text, str)
            or (demo is not None and not isinstance(demo, bool))
            or (provider is not None and not isinstance(provider, str))
        ):
            return jsonify(error="입력 형식이 올바르지 않습니다."), 400
        try:
            return jsonify(
                client().call(
                    "generate",
                    {"request": request_text, "demo": demo, "provider": provider, "project_id": data.get("project_id")},
                )
            ), 202
        except ClientError as exc:
            return _client_error(exc, mutation=True)

    @app.route("/api/projects", methods=["GET", "POST"])
    def projects():
        try:
            if request.method == "POST":
                return jsonify(error="프로젝트 생성은 지원이 종료되었습니다. 대화 세션을 사용하세요."), 410
            return jsonify(client().call("projects.list", {}))
        except ClientError as exc:
            return _client_error(exc)

    @app.put("/api/jobs/<ident>/project")
    def assign_project(ident):
        return jsonify(error="프로젝트 이동은 지원이 종료되었습니다. 대화 세션을 사용하세요."), 410

    @app.get("/api/knowledge/<action>")
    def knowledge(action):
        if action not in {"search", "graph", "node", "document", "impact"}:
            abort(404)
        params = dict(request.args)
        for key in ("depth", "limit", "offset"):
            if key in params:
                try:
                    params[key] = int(params[key])
                except ValueError:
                    return jsonify(error="조회 범위가 올바르지 않습니다."), 400
        try:
            response = jsonify(client().call("knowledge." + action, params))
            response.headers["Cache-Control"] = "no-store"
            return response
        except ClientError as exc:
            return _client_error(exc)

    @app.post("/api/knowledge/retry")
    def retry_embeddings():
        _json()
        try:
            return jsonify(client().call("knowledge.retry", {})), 202
        except ClientError as exc:
            return _client_error(exc, mutation=True)

    @app.post("/api/knowledge/impact")
    def impact_analyse():
        payload = _json()
        try:
            response = jsonify(client().call("knowledge.impact.analyse", payload))
            response.headers["Cache-Control"] = "no-store"
            return response
        except ClientError as exc:
            return _client_error(exc, mutation=True)

    @app.post("/api/jobs/<ident>/<action>")
    def action(ident, action):
        if action not in {"answer", "revise", "approve", "continue"}:
            abort(404)
        data = _json()
        try:
            return jsonify(client().call(action, {"id": ident, "payload": data.get("payload"), "execution_id": data.get("execution_id")})), 202
        except ClientError as exc:
            return _client_error(exc, mutation=True)

    @app.get("/api/jobs/<ident>/download")
    def download(ident):
        try:
            payload = client().call("download", {"id": ident})
            if not isinstance(payload, dict) or not isinstance(payload.get("content"), str):
                abort(404)
            content = base64.b64decode(payload["content"], validate=True)
            if len(content) > 4 * 1024 * 1024:
                abort(404)
            return send_file(
                io.BytesIO(content),
                as_attachment=True,
                download_name="FINAL_AGENT_SPEC.md",
                mimetype="text/markdown",
            )
        except ClientError as exc:
            return _client_error(exc)
        except ValueError:
            abort(404)

    @sock.route("/ws/events")
    def events(ws):
        if not _event_origin_allowed():
            ws.close()
            return
        try:
            for event in client().events():
                ws.send(json.dumps(event, ensure_ascii=False))
        except ClientError:
            try:
                ws.send(json.dumps({"event": "server_error"}, ensure_ascii=False))
            except Exception:
                return

    return app


def _json() -> dict:
    origin = request.headers.get("Origin")
    expected=current_app.config.get('PUBLIC_ORIGIN') if current_app.config.get('PUBLIC_MODE') else request.host_url.rstrip('/')
    if (
        request.mimetype != "application/json"
        or request.headers.get("Sec-Fetch-Site") == "cross-site"
        or (origin and origin != expected)
    ):
        abort(400)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400)
    return data


def _event_origin_allowed() -> bool:
    origin = request.headers.get("Origin")
    if current_app.config.get('PUBLIC_MODE'):
        return bool(origin) and origin==current_app.config.get('PUBLIC_ORIGIN')
    return not origin or origin == request.host_url.rstrip("/")


def _client_error(error: ClientError, *, mutation: bool = False):
    current_app.logger.warning('backend request failed endpoint=%s status=%s uncertain=%s cause_type=%s request_id=%s',
                               request.endpoint,error.status,error.uncertain,type(error.__cause__).__name__ if error.__cause__ else 'none',getattr(g,'request_id',''))
    message = str(error)
    if mutation and error.uncertain and not error.response_received:
        message = "응답을 받지 못했습니다. 작업 반영 여부는 작업 기록을 확인하세요."
    elif mutation and error.uncertain:
        message += ' 작업 접수 여부는 작업 기록을 확인하세요.'
    return jsonify(error=message,request_id=getattr(g,'request_id','')), error.status
