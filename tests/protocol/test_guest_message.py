import json

from protocol.messages import parse_request


def test_guest_creation_is_a_valid_rpc_request():
    packet = {"request_id": "guest-request", "method": "auth.guest", "params": {}}
    assert parse_request(json.dumps(packet)) == packet
