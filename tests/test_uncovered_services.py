"""First coverage for the previously untested service modules:
search (query helpers), discovery (ONVIF XML/SOAP parsing, WS-Security),
notify (telegram pairing status derivation), digest (import sanity).

Pure-logic tests only; network and DB paths stay out of scope here.
"""

import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from types import SimpleNamespace

from services.api.routes.telegram import _pairing_status
from services.discovery.onvif import (
    _extract_text,
    _find_all_recursive,
    _find_recursive,
    _is_auth_fault,
    _ws_security_header,
)
from services.search.query import _build_observation_dict, _is_people_intent

# ── search/query.py ───────────────────────────────────────────────


def test_people_intent_detection():
    assert _is_people_intent("who was at the door?") is True
    assert _is_people_intent("any motion in the garage") is False
    assert _is_people_intent("") is False
    assert _is_people_intent(None) is False


def test_build_observation_dict_resolves_camera_name():
    cam_id = uuid.uuid4()
    obs = SimpleNamespace(
        id=uuid.uuid4(),
        camera_id=cam_id,
        started_at=datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc),
        object_detections={"objects": []},
        person_detections=None,
        vlm_description="a quiet porch",
        confidence=0.7,
        thumbnail_path=None,
    )
    out = _build_observation_dict(obs, {cam_id: "Porch"})
    assert out["camera_name"] == "Porch"
    assert out["started_at"].startswith("2026-06-11T12:00")
    out2 = _build_observation_dict(obs, {})
    assert out2["camera_name"] == "Unknown"


# ── discovery/onvif.py ────────────────────────────────────────────

_NS_XML = """<root xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
  <tds:Manufacturer>Hikvision</tds:Manufacturer>
  <tds:Model>DS-2CD2087</tds:Model>
  <tds:Model>Second</tds:Model>
</root>"""


def test_find_recursive_ignores_namespace():
    root = ET.fromstring(_NS_XML)
    found = _find_recursive(root, "Manufacturer")
    assert _extract_text(found) == "Hikvision"
    assert _find_recursive(root, "DoesNotExist") is None


def test_find_all_recursive():
    root = ET.fromstring(_NS_XML)
    assert [_extract_text(e) for e in _find_all_recursive(root, "Model")] == [
        "DS-2CD2087",
        "Second",
    ]


def test_extract_text_handles_none_and_empty():
    assert _extract_text(None) is None
    assert _extract_text(ET.fromstring("<a>  padded  </a>")) == "padded"
    assert _extract_text(ET.fromstring("<a/>")) is None


def test_is_auth_fault():
    fault = ET.fromstring(
        '<e xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
        "<s:Fault><s:Reason>Sender not authorized</s:Reason></s:Fault></e>"
    )
    assert _is_auth_fault(fault) is True
    other = ET.fromstring("<e><Fault><Reason>timeout</Reason></Fault></e>")
    assert _is_auth_fault(other) is False
    assert _is_auth_fault(None) is False


def test_ws_security_header_shape():
    header = _ws_security_header("admin", "secret")
    assert "<Username>admin</Username>" in header
    assert "PasswordDigest" in header
    assert "secret" not in header  # only the digest ships, never the plaintext


# ── notify (telegram pairing status, used by routes + poller UX) ──


def _channel(**kw):
    defaults = dict(
        enabled=True,
        paired_at=datetime.now(timezone.utc),
        chat_id="123",
        last_test_ok=None,
        last_error=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_pairing_status_states():
    assert _pairing_status(_channel()) == "paired"
    assert _pairing_status(_channel(enabled=False)) == "disabled"
    assert _pairing_status(_channel(paired_at=None)) == "pending"
    assert _pairing_status(_channel(chat_id=None)) == "pending"
    assert (
        _pairing_status(_channel(last_test_ok=False, last_error="Forbidden: bot blocked"))
        == "blocked"
    )
    assert _pairing_status(_channel(last_test_ok=False, last_error="boom")) == "error"


# ── digest service (import + loop constants sanity) ───────────────


def test_digest_scheduler_importable():
    from services.digest import scheduler

    assert callable(scheduler.run_digest_loop)
