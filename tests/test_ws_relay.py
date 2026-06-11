"""Cross-process WS relay envelope contract.

The relay is what makes perception/ingestion broadcasts reach browsers
connected to the API container; without it the dashboard is static.
"""

import json

from services.api.ws import relay_envelope_payload


def test_foreign_message_is_delivered():
    raw = json.dumps({"src": "perception-abc", "msg": {"type": "vlm_status", "camera_id": "c1"}})
    payload = relay_envelope_payload(raw, own_src="api-xyz")
    assert payload is not None
    assert json.loads(payload) == {"type": "vlm_status", "camera_id": "c1"}


def test_own_message_is_skipped():
    # The API process already delivered its own broadcast locally; the
    # relay must not double-send it.
    raw = json.dumps({"src": "api-xyz", "msg": {"type": "notification"}})
    assert relay_envelope_payload(raw, own_src="api-xyz") is None


def test_malformed_envelopes_are_dropped():
    assert relay_envelope_payload("not json", own_src="x") is None
    assert relay_envelope_payload(json.dumps(["list"]), own_src="x") is None
    assert relay_envelope_payload(json.dumps({"src": "a", "msg": "str"}), own_src="x") is None
    assert relay_envelope_payload(None, own_src="x") is None
