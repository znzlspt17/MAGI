import json

from protocol.messages import parse_request


def test_guest_creation_is_a_valid_rpc_request():
    packet = {"request_id": "guest-request", "method": "auth.guest", "params": {}}
    assert parse_request(json.dumps(packet)) == packet


def test_alternate_guest_session_survives_protocol_validation():
    packet = {'request_id': 'progress', 'method': 'progress.authorize', 'params': {},
              'session': 'old-session', 'guest_session': 'guest-session'}
    assert parse_request(json.dumps(packet)) == packet
