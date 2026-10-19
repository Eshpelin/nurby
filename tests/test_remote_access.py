"""Tests for the remote-access wizard backend (#183).

No network: STUN parsing runs against crafted bytes, the connectivity
report is stubbed, and the settings store is dict-backed, matching the
pattern in test_system_settings_endpoint.py.
"""

from __future__ import annotations

import asyncio
import struct
import time
import uuid

import pytest
from fastapi import HTTPException

from services.api import remote_connectivity
from services.api.routes import remote_access as ra
from shared.config import settings as app_config


class _FakeUser:
    def __init__(self, role: str = "admin") -> None:
        self.id = uuid.uuid4()
        self.role = role
        self.is_active = True


@pytest.fixture(autouse=True)
def _in_memory_settings(monkeypatch):
    store: dict[str, object] = {}

    async def fake_get_setting(key, default=None):
        return store.get(key, default)

    async def fake_set_setting(key, value):
        store[key] = value

    monkeypatch.setattr("shared.app_settings.get_setting", fake_get_setting)
    monkeypatch.setattr("shared.app_settings.set_setting", fake_set_setting)
    monkeypatch.setattr(ra, "_connectivity_report", _fake_report)
    ra._probes.clear()
    return store


async def _fake_report(domain: str, scheme: str) -> ra.ConnectivityReport:
    return ra.ConnectivityReport(
        public_ip="203.0.113.7",
        domain_addresses=["203.0.113.7"],
        dns_matches_public_ip=True,
        tls_ok=True,
        tls_detail="valid",
        health_ok=True,
        health_detail="HTTP 200",
        ingress_caddy=False,
    )


def _run(coro):
    return asyncio.run(coro)


# ── IP classification ────────────────────────────────────────────────

def test_classify_ip_matrix():
    assert remote_connectivity.classify_ip("8.8.8.8") == "public"
    assert remote_connectivity.classify_ip("192.168.1.50") == "private"
    assert remote_connectivity.classify_ip("10.0.0.4") == "private"
    assert remote_connectivity.classify_ip("100.64.1.1") == "cgnat"
    assert remote_connectivity.classify_ip("127.0.0.1") == "loopback"
    assert remote_connectivity.classify_ip("169.254.3.3") == "linklocal"
    # Documentation ranges are IANA-reserved, not proof of an internet hit.
    assert remote_connectivity.classify_ip("203.0.113.7") == "private"
    assert remote_connectivity.classify_ip("testclient") == "invalid"
    assert remote_connectivity.classify_ip("") == "invalid"


# ── STUN ─────────────────────────────────────────────────────────────

def _stun_binding_response(txid: bytes, ip: str, port: int, xor: bool) -> bytes:
    addr = struct.pack("!4s", __import__("socket").inet_aton(ip))
    out_port = port ^ 0x2112 if xor else port
    if xor:
        addr = bytes(
            b ^ m for b, m in zip(addr, remote_connectivity._STUN_MAGIC_COOKIE)
        )
    attr_type = 0x0020 if xor else 0x0001
    value = struct.pack("!BBH", 0x00, 0x01, out_port) + addr
    attr = struct.pack("!HH", attr_type, len(value)) + value
    header = (
        struct.pack("!HH", 0x0101, len(attr))
        + remote_connectivity._STUN_MAGIC_COOKIE
        + txid
    )
    return header + attr


def test_stun_roundtrip_xor_mapped_address():
    request, txid = remote_connectivity.build_stun_binding_request()
    assert len(request) == 20
    response = _stun_binding_response(txid, "203.0.113.7", 5555, xor=True)
    assert remote_connectivity.parse_stun_binding_response(response, txid) == "203.0.113.7"


def test_stun_roundtrip_mapped_address_fallback():
    _request, txid = remote_connectivity.build_stun_binding_request()
    response = _stun_binding_response(txid, "198.51.100.9", 3478, xor=False)
    assert remote_connectivity.parse_stun_binding_response(response, txid) == "198.51.100.9"


def test_stun_rejects_mismatched_transaction_and_garbage():
    _request, txid = remote_connectivity.build_stun_binding_request()
    other_txid = bytes(12)
    response = _stun_binding_response(other_txid, "203.0.113.7", 5555, xor=True)
    assert remote_connectivity.parse_stun_binding_response(response, txid) is None
    assert remote_connectivity.parse_stun_binding_response(b"garbage", txid) is None


# ── Configured URL resolution ────────────────────────────────────────

def test_configured_url_db_wins_over_env(monkeypatch):
    monkeypatch.setattr(app_config, "public_base_url", "https://env.example.com")
    scheme, host = _run(ra.configured_public_url())
    assert (scheme, host) == ("https", "env.example.com")


def test_configured_url_empty_without_any_source(monkeypatch):
    monkeypatch.setattr(app_config, "public_base_url", None)
    assert _run(ra.configured_public_url()) == (None, None)


# ── Domain validation ────────────────────────────────────────────────

def test_set_domain_stores_https_url():
    store = ra  # noqa: F841 (documentation of scope)
    state = _run(ra.set_remote_access_domain(ra.DomainBody(domain="Camera.Example.com"), _current_user=_FakeUser()))
    assert state.domain == "camera.example.com"
    assert state.public_base_url == "https://camera.example.com"
    from shared.app_settings import get_setting
    assert _run(get_setting("public_base_url")) == "https://camera.example.com"


@pytest.mark.parametrize(
    "bad",
    [
        "https://camera.example.com",
        "camera.example.com/path",
        "not a domain",
        "localhost",
        "-dot.com",
        "",
    ],
)
def test_set_domain_rejects_non_hostnames(bad):
    with pytest.raises(HTTPException) as exc:
        _run(ra.set_remote_access_domain(ra.DomainBody(domain=bad), _current_user=_FakeUser()))
    assert exc.value.status_code == 400


def test_clear_domain_resets_state_and_probes():
    _run(ra.set_remote_access_domain(ra.DomainBody(domain="camera.example.com"), _current_user=_FakeUser()))
    ra._new_probe("camera.example.com")
    state = _run(ra.clear_remote_access_domain(_current_user=_FakeUser()))
    assert state.configured is False
    assert ra._active_probe() is None


# ── Phone probe: the fail-closed core ────────────────────────────────

def test_probe_verifies_only_from_public_source_over_https():
    probe = ra._new_probe("camera.example.com")
    assert ra.register_probe_hit(probe.nonce, "192.168.1.20", "https") == "waiting"
    assert ra._active_probe().verified is False
    assert ra.register_probe_hit(probe.nonce, "9.9.9.9", "https") == "verified"
    assert ra._active_probe().verified is True
    assert ra._active_probe().verified_from == "9.9.9.9"


def test_probe_never_verifies_over_plain_http():
    probe = ra._new_probe("camera.example.com")
    assert ra.register_probe_hit(probe.nonce, "9.9.9.9", "http") == "insecure"
    assert ra._active_probe().verified is False


def test_probe_unknown_nonce_and_expiry():
    assert ra.register_probe_hit("nope", "9.9.9.9", "https") == "unknown"
    probe = ra._new_probe("camera.example.com")
    ra._probes[probe.nonce]["created"] = time.monotonic() - 601
    assert ra.register_probe_hit(probe.nonce, "9.9.9.9", "https") == "unknown"


def test_probe_verifies_from_cgnat_range():
    # A phone on carrier-grade NAT still has a public-side source address
    # from our vantage point only if it's outside 100.64/10; inside that
    # range the hit cannot be trusted as "from the internet".
    probe = ra._new_probe("camera.example.com")
    assert ra.register_probe_hit(probe.nonce, "100.64.9.9", "https") == "waiting"


def test_start_probe_requires_https_url(monkeypatch):
    monkeypatch.setattr(app_config, "public_base_url", "http://lan.example.com")
    with pytest.raises(HTTPException) as exc:
        _run(ra.start_probe(_current_user=_FakeUser()))
    assert exc.value.status_code == 400


def test_probe_rate_limit_blocks_flood():
    source = "198.51.100.77"
    now = time.monotonic()
    for _ in range(ra._PROBE_RATE_LIMIT):
        assert ra._probe_rate_ok(source, now)
    assert not ra._probe_rate_ok(source, now)
    # A different source is unaffected.
    assert ra._probe_rate_ok("198.51.100.78", now)
