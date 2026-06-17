"""Outbound webhook target policy.

Nurby is self-hosted and LAN webhooks are a first-class feature (ESP32
sirens, relays, n8n on the same box), so private addresses are ALLOWED by
default. Two layers exist on top of that:

1. Cloud metadata endpoints are always refused. No home automation lives
   at 169.254.169.254, and on a cloud-hosted Nurby that address leaks
   instance credentials.
2. The ``webhook_block_private_networks`` app setting (default off) lets a
   hardened deployment opt into refusing loopback/private/link-local
   targets entirely, e.g. when rule-editing users are less trusted than
   the host.

Resolution happens at send time and is best-effort: a DNS name that
re-resolves between check and request (DNS rebinding) is out of scope for
a self-hosted product; the always-on metadata block checks the literal
host as well as its resolution.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

__all__ = [
    "webhook_target_rejection",
    "stream_target_rejection",
    "stream_target_rejection_sync",
]

# Always refused, regardless of settings.
_METADATA_HOSTS = {
    "169.254.169.254",  # AWS/GCP/Azure instance metadata
    "metadata.google.internal",
    "metadata.goog",
}


def _addresses_for(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Literal IP or resolved A/AAAA records. Empty when resolution fails
    (the request itself will then fail with a clearer error)."""
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        out = []
        for info in infos:
            try:
                out.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
        return out
    except OSError:
        return []


def _rejection_sync(url: str, block_private: bool) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return "invalid URL"
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return "URL has no host"

    if host in _METADATA_HOSTS:
        return f"refusing cloud metadata endpoint {host}"
    addresses = _addresses_for(host)
    for addr in addresses:
        if addr.is_link_local and str(addr).startswith("169.254.169."):
            return f"refusing cloud metadata address {addr}"

    if block_private:
        for addr in addresses:
            if addr.is_loopback or addr.is_private or addr.is_link_local:
                return (
                    f"{host} resolves to a private address ({addr}) and "
                    "webhook_block_private_networks is enabled"
                )
    return None


async def webhook_target_rejection(url: str) -> str | None:
    """Reason this webhook target must be refused, or None when allowed.

    Reads the ``webhook_block_private_networks`` app setting; DNS work runs
    off the event loop.
    """
    from shared.app_settings import get_setting

    try:
        block_private = bool(await get_setting("webhook_block_private_networks", False))
    except Exception:
        block_private = False
    return await asyncio.to_thread(_rejection_sync, url, block_private)


# ── Camera stream targets (SSRF) ──────────────────────────────────────
#
# http_snapshot / http_mjpeg / hls camera URLs are operator-supplied and
# fetched server-side, which is a classic SSRF lever: a malicious or
# poisoned camera row can point the ingestion worker at an internal
# service or the cloud metadata endpoint and exfiltrate the response into
# decoded "frames". The scheme allowlist (PR #34, shared/schemas.py)
# closes file:// / gopher:// etc.; this closes the host/IP dimension.
#
# Cloud metadata and loopback / link-local addresses can never be a real
# camera, so they are refused unconditionally. RFC1918 private ranges
# (10/8, 172.16/12, 192.168/16) ARE legitimate for LAN cameras on a
# self-hosted box, so they are only refused when the operator opts into
# the ``camera_block_private_networks`` hardening setting (default off),
# mirroring ``webhook_block_private_networks``.


def stream_target_rejection_sync(url: str, block_private: bool = False) -> str | None:
    """Reason this camera stream URL must be refused, or None when allowed.

    Always refuses cloud metadata, loopback (127/8, ::1) and link-local
    (169.254/16, fe80::/10) targets. RFC1918 private ranges are refused
    only when ``block_private`` is set.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return "invalid URL"
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return "URL has no host"

    if host in _METADATA_HOSTS:
        return f"refusing cloud metadata endpoint {host}"
    addresses = _addresses_for(host)
    for addr in addresses:
        if addr.is_link_local and str(addr).startswith("169.254.169."):
            return f"refusing cloud metadata address {addr}"

    # Loopback and link-local can never be a legitimate camera; always refuse.
    for addr in addresses:
        if addr.is_loopback:
            return f"refusing loopback stream target {addr}"
        if addr.is_link_local:
            return f"refusing link-local stream target {addr}"

    if block_private:
        for addr in addresses:
            if addr.is_private:
                return (
                    f"{host} resolves to a private address ({addr}) and "
                    "camera_block_private_networks is enabled"
                )
    return None


async def stream_target_rejection(url: str) -> str | None:
    """Reason this camera stream URL must be refused, or None when allowed.

    Reads the ``camera_block_private_networks`` app setting; DNS work runs
    off the event loop. Loopback / link-local / metadata are always
    refused regardless of the setting.
    """
    from shared.app_settings import get_setting

    try:
        block_private = bool(await get_setting("camera_block_private_networks", False))
    except Exception:
        block_private = False
    return await asyncio.to_thread(stream_target_rejection_sync, url, block_private)
