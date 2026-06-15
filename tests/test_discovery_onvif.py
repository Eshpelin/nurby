"""Deeper coverage for services/discovery/onvif.py.

The existing suite covers the namespace-agnostic finders, ``_extract_text``,
``_is_auth_fault`` and the WS-Security header shape. This file adds:

  * device-probe orchestration (``_probe_device``) across the four SOAP
    calls, with the SOAP transport stubbed so no socket is opened,
  * GetProfiles / GetStreamUri / GetCapabilities response-shape parsing,
  * PTZ service-URL building and PTZ preset response parsing,
  * WS-Security PasswordDigest correctness (digest == b64(sha1(nonce +
    created + password))).

All XML is parsed with the real stdlib ``ElementTree`` so we exercise the
genuine namespace-stripping finder logic.
"""

import hashlib
import xml.etree.ElementTree as ET
from base64 import b64decode, b64encode

import pytest

from services.discovery import onvif as onvif

# ── SOAP response fixtures ─────────────────────────────────────────

_DEVICE_INFO_XML = """<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
  xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
 <s:Body><tds:GetDeviceInformationResponse>
  <tds:Manufacturer>Hikvision</tds:Manufacturer>
  <tds:Model>DS-2CD2087</tds:Model>
  <tds:FirmwareVersion>V5.6.3</tds:FirmwareVersion>
 </tds:GetDeviceInformationResponse></s:Body></s:Envelope>"""

_CAPABILITIES_XML = """<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
  xmlns:tt="http://www.onvif.org/ver10/schema">
 <s:Body><GetCapabilitiesResponse><Capabilities>
   <Media><XAddr>http://10.0.0.5:80/onvif/media2</XAddr></Media>
 </Capabilities></GetCapabilitiesResponse></s:Body></s:Envelope>"""

_PROFILES_XML = """<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
  xmlns:trt="http://www.onvif.org/ver10/media/wsdl"
  xmlns:tt="http://www.onvif.org/ver10/schema">
 <s:Body><trt:GetProfilesResponse>
   <trt:Profiles token="Profile_1">
     <tt:Name>mainstream</tt:Name>
     <tt:VideoEncoderConfiguration>
       <tt:Resolution><tt:Width>1920</tt:Width><tt:Height>1080</tt:Height></tt:Resolution>
     </tt:VideoEncoderConfiguration>
   </trt:Profiles>
   <trt:Profiles token="Profile_2">
     <tt:Name>substream</tt:Name>
   </trt:Profiles>
 </trt:GetProfilesResponse></s:Body></s:Envelope>"""

_STREAM_URI_XML = """<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
  xmlns:trt="http://www.onvif.org/ver10/media/wsdl"
  xmlns:tt="http://www.onvif.org/ver10/schema">
 <s:Body><trt:GetStreamUriResponse><trt:MediaUri>
   <tt:Uri>rtsp://10.0.0.5:554/Streaming/Channels/101</tt:Uri>
 </trt:MediaUri></trt:GetStreamUriResponse></s:Body></s:Envelope>"""

_AUTH_FAULT_XML = """<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">
 <s:Body><s:Fault><s:Code><s:Value>s:Sender</s:Value></s:Code>
   <s:Reason><s:Text>Sender not authorized</s:Text></s:Reason>
 </s:Fault></s:Body></s:Envelope>"""

_PRESETS_XML = """<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
  xmlns:ptz="http://www.onvif.org/ver20/ptz/wsdl"
  xmlns:tt="http://www.onvif.org/ver10/schema">
 <s:Body><ptz:GetPresetsResponse>
   <ptz:Preset token="1"><tt:Name>Front Gate</tt:Name></ptz:Preset>
   <ptz:Preset token="2"><tt:Name>Driveway</tt:Name></ptz:Preset>
   <ptz:Preset token="3"></ptz:Preset>
 </ptz:GetPresetsResponse></s:Body></s:Envelope>"""


def _route_by_envelope(envelope: str):
    """Return the canned root matching the SOAP action in the envelope."""
    if "GetDeviceInformation" in envelope:
        return ET.fromstring(_DEVICE_INFO_XML)
    if "GetCapabilities" in envelope:
        return ET.fromstring(_CAPABILITIES_XML)
    if "GetProfiles" in envelope:
        return ET.fromstring(_PROFILES_XML)
    if "GetStreamUri" in envelope:
        return ET.fromstring(_STREAM_URI_XML)
    return None


def _install_soap(monkeypatch, router):
    """Patch the SOAP transport so _probe_device never opens a socket."""

    async def _fake_soap(client, url, envelope, timeout=3.0):
        return router(envelope)

    monkeypatch.setattr(onvif, "_soap_request", _fake_soap)


# ── _probe_device: full happy path ─────────────────────────────────


@pytest.mark.asyncio
async def test_probe_device_parses_full_chain(monkeypatch):
    _install_soap(monkeypatch, _route_by_envelope)

    out = await onvif._probe_device("http://10.0.0.5:80/onvif/device_service", client=None)
    assert out is not None
    assert out["ip"] == "10.0.0.5"
    assert out["port"] == 80
    assert out["manufacturer"] == "Hikvision"
    assert out["model"] == "DS-2CD2087"
    assert out["name"] == "Hikvision DS-2CD2087"
    assert out["firmware"] == "V5.6.3"
    assert out["profiles"] == ["mainstream", "substream"]
    assert out["resolution"] == "1920x1080"
    assert out["stream_url"] == "rtsp://10.0.0.5:554/Streaming/Channels/101"
    assert out["auth_required"] is False


@pytest.mark.asyncio
async def test_probe_device_default_port_when_url_omits_it(monkeypatch):
    _install_soap(monkeypatch, _route_by_envelope)
    out = await onvif._probe_device("http://192.168.1.9/onvif/device_service", client=None)
    assert out["ip"] == "192.168.1.9"
    assert out["port"] == 80  # falls back to 80 when the URL has no port


@pytest.mark.asyncio
async def test_probe_device_marks_auth_required_on_device_info_fault(monkeypatch):
    def router(envelope):
        if "GetDeviceInformation" in envelope:
            return ET.fromstring(_AUTH_FAULT_XML)
        return _route_by_envelope(envelope)

    _install_soap(monkeypatch, router)
    out = await onvif._probe_device("http://10.0.0.5:80/onvif/device_service", client=None)
    # Device info faulted, so manufacturer/model stay at defaults and the
    # auth flag flips. Later calls still succeed in this fixture.
    assert out["auth_required"] is True
    assert out["manufacturer"] == "Unknown"
    assert out["model"] == "Unknown"


@pytest.mark.asyncio
async def test_probe_device_unreachable_device_info(monkeypatch):
    def router(envelope):
        if "GetDeviceInformation" in envelope:
            return None  # transport returned nothing (timeout / 401)
        return _route_by_envelope(envelope)

    _install_soap(monkeypatch, router)
    out = await onvif._probe_device("http://10.0.0.5:80/onvif/device_service", client=None)
    assert out["auth_required"] is True


@pytest.mark.asyncio
async def test_probe_device_uses_capabilities_media_xaddr(monkeypatch):
    """The media_url used for GetProfiles/GetStreamUri comes from the
    capabilities Media XAddr when present, not the naive /media_service swap."""
    seen_urls = []

    async def _fake_soap(client, url, envelope, timeout=3.0):
        seen_urls.append((url, envelope))
        return _route_by_envelope(envelope)

    monkeypatch.setattr(onvif, "_soap_request", _fake_soap)

    await onvif._probe_device("http://10.0.0.5:80/onvif/device_service", client=None)
    # GetProfiles must have been sent to the XAddr from capabilities.
    profiles_url = next(u for (u, e) in seen_urls if "GetProfiles" in e)
    assert profiles_url == "http://10.0.0.5:80/onvif/media2"


@pytest.mark.asyncio
async def test_probe_device_no_profiles_yields_empty_list(monkeypatch):
    def router(envelope):
        if "GetProfiles" in envelope:
            # Valid envelope but zero Profiles elements.
            return ET.fromstring(
                '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
                "<s:Body><GetProfilesResponse/></s:Body></s:Envelope>"
            )
        return _route_by_envelope(envelope)

    _install_soap(monkeypatch, router)
    out = await onvif._probe_device("http://10.0.0.5:80/onvif/device_service", client=None)
    assert out["profiles"] == []
    assert out["stream_url"] is None  # no profile token -> no stream query


# ── PTZ service URL ────────────────────────────────────────────────


def test_ptz_service_url_format():
    assert onvif._ptz_service_url("10.0.0.7", 8080) == "http://10.0.0.7:8080/onvif/ptz_service"
    assert onvif._ptz_service_url("cam.local", 80) == "http://cam.local:80/onvif/ptz_service"


# ── PTZ preset response parsing ────────────────────────────────────


@pytest.mark.asyncio
async def test_ptz_get_presets_parses_tokens_and_names(monkeypatch):
    async def _fake_cmd(ip, port, username, password, template, **kw):
        return ET.fromstring(_PRESETS_XML)

    monkeypatch.setattr(onvif, "_ptz_command", _fake_cmd)
    presets = await onvif.ptz_get_presets("10.0.0.7", 80, "u", "p", "Profile_1")
    assert presets == [
        {"token": "1", "name": "Front Gate"},
        {"token": "2", "name": "Driveway"},
        {"token": "3", "name": "3"},  # missing Name falls back to the token
    ]


@pytest.mark.asyncio
async def test_ptz_get_presets_empty_on_auth_fault(monkeypatch):
    async def _fake_cmd(ip, port, username, password, template, **kw):
        return ET.fromstring(_AUTH_FAULT_XML)

    monkeypatch.setattr(onvif, "_ptz_command", _fake_cmd)
    assert await onvif.ptz_get_presets("10.0.0.7", 80, "u", "p", "Profile_1") == []


@pytest.mark.asyncio
async def test_ptz_get_presets_empty_on_no_response(monkeypatch):
    async def _fake_cmd(ip, port, username, password, template, **kw):
        return None

    monkeypatch.setattr(onvif, "_ptz_command", _fake_cmd)
    assert await onvif.ptz_get_presets("10.0.0.7", 80, "u", "p", "Profile_1") == []


# ── PTZ commands return True only on clean (non-fault) response ────


@pytest.mark.asyncio
async def test_ptz_continuous_move_true_on_ok(monkeypatch):
    async def _ok(ip, port, username, password, template, **kw):
        return ET.fromstring("<resp/>")

    monkeypatch.setattr(onvif, "_ptz_command", _ok)
    assert await onvif.ptz_continuous_move("ip", 80, "u", "p", "Profile_1", 0.5, 0.0, 0.0) is True


@pytest.mark.asyncio
async def test_ptz_continuous_move_false_on_fault(monkeypatch):
    async def _fault(ip, port, username, password, template, **kw):
        return ET.fromstring(_AUTH_FAULT_XML)

    monkeypatch.setattr(onvif, "_ptz_command", _fault)
    assert await onvif.ptz_continuous_move("ip", 80, "u", "p", "Profile_1", 0.5, 0.0, 0.0) is False


@pytest.mark.asyncio
async def test_ptz_stop_false_on_none(monkeypatch):
    async def _none(ip, port, username, password, template, **kw):
        return None

    monkeypatch.setattr(onvif, "_ptz_command", _none)
    assert await onvif.ptz_stop("ip", 80, "u", "p", "Profile_1") is False


@pytest.mark.asyncio
async def test_ptz_goto_preset_true_on_ok(monkeypatch):
    async def _ok(ip, port, username, password, template, **kw):
        # The envelope must carry both profile and preset tokens.
        assert kw["profile_token"] == "Profile_1"
        assert kw["preset_token"] == "2"
        return ET.fromstring("<resp/>")

    monkeypatch.setattr(onvif, "_ptz_command", _ok)
    assert await onvif.ptz_goto_preset("ip", 80, "u", "p", "Profile_1", "2") is True


# ── _ptz_command header selection (no auth -> bare header) ─────────


@pytest.mark.asyncio
async def test_ptz_command_uses_security_header_only_with_creds(monkeypatch):
    captured = {}

    async def _fake_soap(client, url, envelope, timeout=5.0):
        captured["envelope"] = envelope
        captured["url"] = url
        return ET.fromstring("<ok/>")

    monkeypatch.setattr(onvif, "_soap_request", _fake_soap)

    # With creds: WS-Security header is injected.
    await onvif._ptz_command(
        "10.0.0.7", 80, "admin", "secret",
        onvif._PTZ_STOP_ENVELOPE, profile_token="P1",
    )
    assert "<Username>admin</Username>" in captured["envelope"]
    assert captured["url"] == "http://10.0.0.7:80/onvif/ptz_service"

    # Without creds: a bare <s:Header/> is used, no UsernameToken.
    await onvif._ptz_command(
        "10.0.0.7", 80, None, None,
        onvif._PTZ_STOP_ENVELOPE, profile_token="P1",
    )
    assert "<s:Header/>" in captured["envelope"]
    assert "UsernameToken" not in captured["envelope"]


# ── WS-Security PasswordDigest correctness ─────────────────────────


def test_ws_security_digest_matches_spec():
    header = onvif._ws_security_header("admin", "pa55w0rd")
    # The header is a fragment that uses the s: prefix; it's meant to be
    # spliced into a full SOAP envelope. Wrap it so the prefix resolves,
    # mirroring how _ptz_command embeds it.
    wrapped = (
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
        f"{header}</s:Envelope>"
    )
    root = ET.fromstring(wrapped)

    def _local(name):
        for el in root.iter():
            if el.tag.endswith("}" + name) or el.tag == name:
                return el
        return None

    nonce_b64 = _local("Nonce").text
    created = _local("Created").text
    digest_b64 = _local("Password").text
    username = _local("Username").text

    assert username == "admin"
    # Recompute the digest per ONVIF: b64(sha1(nonce_bytes + created + password)).
    nonce_bytes = b64decode(nonce_b64)
    expected = b64encode(
        hashlib.sha1(nonce_bytes + created.encode() + b"pa55w0rd").digest()
    ).decode()
    assert digest_b64 == expected
    # The plaintext password must never appear in the header.
    assert "pa55w0rd" not in header


def test_ws_security_password_type_is_digest():
    header = onvif._ws_security_header("u", "p")
    assert "#PasswordDigest" in header
    assert "Created" in header and "Nonce" in header
