import json

from gateway.client import ClientError
from gateway.progress import serve_progress


def test_linked_guest_job_subscribes_to_its_verified_owner():
    job = 'a' * 32
    class Client:
        def call(self, method, params=None):
            if method == 'progress.authorize':
                return {'id': 'account', 'owner_ids': ['account', 'guest'],
                        **({'owner_id': 'guest'} if params else {})}
            if method == 'progress.list':
                return {'jobs': [], 'revisions': {}}
            if method == 'progress.snapshot':
                return {'event': 'job.snapshot', 'job_id': job}
            raise AssertionError(method)
    class Hub:
        def __init__(self): self.attached = []
        def attach(self, listener, job=None, owner=None): self.attached.append((owner or listener.owner, job))
        def detach(self, listener, key=None): pass
    class Socket:
        calls = 0
        def send(self, value): pass
        def receive(self, timeout):
            self.calls += 1
            if self.calls == 1:
                return json.dumps({'event': 'job.subscribe', 'job_id': job})
            raise ClientError('expired', status=401)
        def close(self): pass
    hub = Hub()
    serve_progress(Socket(), Client(), hub)
    assert ('account', None) in hub.attached
    assert ('guest', None) in hub.attached
    assert ('guest', job) in hub.attached


def test_linked_account_refreshes_existing_socket_list_on_scope_change(monkeypatch):
    import gateway.progress as progress
    job = 'b' * 32
    ticks = iter([0, 31, 31])
    monkeypatch.setattr(progress.time, 'monotonic', lambda: next(ticks, 31))

    class Client:
        auth_calls = 0
        def call(self, method, params=None):
            if method == 'progress.authorize':
                self.auth_calls += 1
                return {'id': 'account', 'owner_ids': ['account'] if self.auth_calls == 1 else ['account', 'guest']}
            if method == 'progress.list':
                return {'jobs': [] if self.auth_calls == 1 else [{'id': job}], 'revisions': {}}
            if method == 'service.status': return {}
            raise AssertionError(method)
    class Hub:
        def attach(self, listener, job=None, owner=None): pass
        def detach(self, listener, key=None): pass
    class Socket:
        def __init__(self): self.messages = []; self.calls = 0
        def send(self, value): self.messages.append(json.loads(value))
        def receive(self, timeout):
            self.calls += 1
            if self.calls > 1: raise ClientError('expired', status=401)
            return None
        def close(self): pass
    socket = Socket()
    serve_progress(socket, Client(), Hub())
    snapshots = [message for message in socket.messages if message['event'] == 'jobs.snapshot']
    assert [snapshot['jobs'] for snapshot in snapshots] == [[], [{'id': job}]]


def test_scope_change_detected_by_event_refreshes_snapshot_before_event():
    job = 'c' * 32
    class Client:
        auth_calls = 0
        def call(self, method, params=None):
            if method == 'progress.authorize':
                self.auth_calls += 1
                return {'id': 'account', 'owner_ids': ['account'] if self.auth_calls == 1 else ['account', 'guest']}
            if method == 'progress.list':
                return {'jobs': [] if self.auth_calls == 1 else [{'id': job}], 'revisions': {}}
            raise AssertionError(method)
    class Hub:
        def attach(self, listener, job=None, owner=None):
            if owner is None:
                listener.put({'event': 'jobs.changed', 'job_id': 'a' * 32})
        def detach(self, listener, key=None): pass
    class Socket:
        def __init__(self): self.messages = []; self.calls = 0
        def send(self, value): self.messages.append(json.loads(value))
        def receive(self, timeout):
            self.calls += 1
            if self.calls > 1: raise ClientError('expired', status=401)
            return None
        def close(self): pass
    socket = Socket()
    serve_progress(socket, Client(), Hub())
    assert [message['event'] for message in socket.messages[:4]] == ['ready', 'jobs.snapshot', 'jobs.snapshot', 'jobs.changed']
    assert socket.messages[2]['jobs'] == [{'id': job}]
