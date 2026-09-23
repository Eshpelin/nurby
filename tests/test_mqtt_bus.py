"""Tests for the MQTT publish bus envelope codec (shared/mqtt_bus.py)."""

import base64

from shared.mqtt_bus import decode_bus_message


def test_decode_string_payload():
    out = decode_bus_message('{"t": "nurby/events", "s": "{\\"a\\": 1}", "r": true}')
    assert out == ("nurby/events", b'{"a": 1}', True)


def test_decode_binary_payload_is_base64():
    import json

    jpeg = bytes(range(256))
    env = {"t": "nurby/cameras/x/snapshot", "b": base64.b64encode(jpeg).decode(), "r": False}
    decoded = decode_bus_message(json.dumps(env))
    assert decoded == ("nurby/cameras/x/snapshot", jpeg, False)


def test_decode_rejects_malformed_envelopes():
    assert decode_bus_message("not json") is None
    assert decode_bus_message('{"no_topic": true}') is None
    assert decode_bus_message('{"t": "a", "r": false}') is None  # no payload
    assert decode_bus_message('{"t": "a", "b": "!!!not-base64!!!"}') is None
    assert decode_bus_message("42") is None
