"""Webhook target policy coverage.

LAN targets are allowed by default (ESP32 sirens and n8n on the LAN are a
feature); cloud metadata endpoints are always refused; the
webhook_block_private_networks setting opts a hardened deploy into
refusing private ranges entirely.
"""

from shared.netpolicy import _rejection_sync


def test_lan_target_allowed_by_default():
    assert _rejection_sync("http://192.168.1.50/siren", block_private=False) is None
    assert _rejection_sync("http://10.0.0.7:1880/webhook", block_private=False) is None
    assert _rejection_sync("http://localhost:5678/n8n", block_private=False) is None


def test_public_target_allowed():
    assert _rejection_sync("https://hooks.example.com/x", block_private=False) is None


def test_metadata_endpoint_always_refused():
    assert _rejection_sync("http://169.254.169.254/latest/meta-data/", False) is not None
    assert _rejection_sync("http://169.254.169.254/latest/meta-data/", True) is not None
    assert _rejection_sync("http://metadata.google.internal/computeMetadata/", False) is not None


def test_block_private_refuses_lan_when_enabled():
    assert _rejection_sync("http://192.168.1.50/siren", block_private=True) is not None
    assert _rejection_sync("http://127.0.0.1:6379/", block_private=True) is not None
    assert _rejection_sync("http://[::1]:8000/", block_private=True) is not None


def test_block_private_still_allows_public():
    assert _rejection_sync("https://example.com/hook", block_private=True) is None


def test_garbage_url_refused():
    assert _rejection_sync("not-a-url", block_private=False) is not None
    assert _rejection_sync("", block_private=False) is not None
