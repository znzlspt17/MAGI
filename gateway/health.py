"""프록시에서 공개하지 않는 loopback 전용 상태 경로."""

from ipaddress import ip_address

from flask import abort, jsonify, request

from gateway.frontend import frontend_assets


def install_health(app, client):
    def local_only():
        try:
            local = ip_address(request.remote_addr or '').is_loopback
        except ValueError:
            local = False
        if not local:
            abort(404)

    @app.get('/health/live')
    def live():
        local_only()
        return jsonify(alive=True)

    @app.get('/health/ready')
    def ready():
        local_only()
        try:
            frontend_assets()
            if client().call('health.check') != {'ready': True}:
                raise ValueError
        except Exception:
            return jsonify(ready=False), 503
        return jsonify(ready=True)
