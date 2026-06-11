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

__all__ = ["webhook_target_rejection"]

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
