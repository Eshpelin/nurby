"""Remote-access connectivity checks (#183).

Pure, individually testable building blocks behind Settings → Remote
access: STUN public-IP discovery, DNS cross-check, TLS handshake
validation, HTTP health reachability, and source-IP classification for
the phone-assisted reachability probe.

Nothing here opens a listening socket or weakens the default posture:
STUN sends one UDP datagram to a public server, everything else is an
outbound check.
"""

import asyncio
import ipaddress
import logging
import os
import socket
import ssl
import struct

import httpx

logger = logging.getLogger("nurby.api.remote_connectivity")

# Overridable for self-hosted/privacy-conscious installs; comma-separated
# host:port pairs.
DEFAULT_STUN_SERVERS = ("stun.l.google.com:19302",)

_STUN_MAGIC_COOKIE = b"\x21\x12\xa4\x42"


def stun_servers() -> list[str]:
    raw = os.environ.get("NURBY_STUN_SERVERS", "")
    servers = [s.strip() for s in raw.split(",") if s.strip()]
    return servers or list(DEFAULT_STUN_SERVERS)


def build_stun_binding_request() -> tuple[bytes, bytes]:
    """A minimal RFC 5389 binding request. Returns (packet, transaction_id)."""
    txid = os.urandom(12)
    packet = struct.pack("!HH", 0x0001, 0) + _STUN_MAGIC_COOKIE + txid
    return packet, txid


def parse_stun_binding_response(data: bytes, txid: bytes) -> str | None:
    """Observed public IPv4 from a binding response, or None.

    Prefers XOR-MAPPED-ADDRESS (RFC 5389), falls back to MAPPED-ADDRESS
    (RFC 3489). The response header must echo the transaction id we sent,
    so a stray datagram can't poison the result.
    """
    if len(data) < 20:
        return None
    msg_type, msg_len = struct.unpack("!HH", data[:4])
    if msg_type != 0x0101 or data[4:8] != _STUN_MAGIC_COOKIE or data[8:20] != txid:
        return None
    xor = mapped = None
    offset = 20
    end = min(20 + msg_len, len(data))
    while offset + 4 <= end:
        attr_type, attr_len = struct.unpack("!HH", data[offset : offset + 4])
        value = data[offset + 4 : offset + 4 + attr_len]
        if attr_type == 0x0020:
            xor = _decode_stun_address(value, xor_=True)
        elif attr_type == 0x0001:
            mapped = _decode_stun_address(value, xor_=False)
        offset += 4 + attr_len + ((4 - attr_len % 4) % 4)
    return xor or mapped


def _decode_stun_address(value: bytes, xor_: bool) -> str | None:
    if len(value) < 8:
        return None
    family = value[1]
    if family != 0x01:  # IPv4 only; the ingress story is a single v4 A record.
        return None
    port = struct.unpack("!H", value[2:4])[0]
    addr = struct.unpack("!4s", value[4:8])[0]
    if xor_:
        port ^= 0x2112
        addr = bytes(b ^ m for b, m in zip(addr, _STUN_MAGIC_COOKIE))
    try:
        return socket.inet_ntoa(addr)
    except OSError:
        return None


async def stun_public_ip(timeout: float = 3.0) -> str | None:
    """Ask a public STUN server what address it saw us come from.

    Returns None when every server is unreachable or times out — callers
    treat that as "unknown", never as "not reachable".
    """
    loop = asyncio.get_running_loop()
    for server in stun_servers():
        host, _, port = server.partition(":")
        try:
            infos = await loop.getaddrinfo(
                host, int(port or 3478), type=socket.SOCK_DGRAM
            )
            family, socktype, proto, _canonical, sockaddr = infos[0]
            with socket.socket(family, socktype, proto) as sock:
                sock.setblocking(False)
                request, txid = build_stun_binding_request()
                await asyncio.wait_for(
                    loop.sock_sendto(sock, request, sockaddr), timeout
                )
                deadline = timeout
                while deadline > 0:
                    data = await asyncio.wait_for(
                        loop.sock_recv(sock, 2048), timeout=deadline
                    )
                    observed = parse_stun_binding_response(data, txid)
                    if observed:
                        return observed
                    # Unmatched datagram (late reply from an earlier
                    # request): keep listening for the remainder.
                    deadline -= timeout
        except Exception as exc:
            logger.debug("STUN %s failed: %s", server, exc)
            continue
    return None


async def resolve_domain_ips(domain: str) -> list[str]:
    """Unique IPv4 addresses the domain currently resolves to."""
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(domain, 443, type=socket.SOCK_STREAM), timeout=5.0
        )
    except Exception:
        return []
    seen: list[str] = []
    for info in infos:
        addr = info[4][0]
        if isinstance(addr, str) and addr not in seen and ":" not in addr:
            seen.append(addr)
    return seen


def classify_ip(ip: str) -> str:
    """Where does this source address live?

    "public" means a real internet address: the only kind that can prove
    outside reachability for the phone probe. Classification uses the
    IANA special-purpose registry semantics (``is_global``), not just
    RFC 1918 — documentation and benchmark ranges are not proof of an
    internet-path hit either. "cgnat" (carrier-grade NAT, RFC 6598) is
    separated out because it also answers the wizard's "which path
    applies to you" question.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "invalid"
    # The IANA special-purpose registry is the source of truth for "this
    # address exists on the public internet": is_global covers RFC 1918,
    # documentation (TEST-NET), benchmark, and Carrier NAT ranges alike.
    if addr.is_global:
        return "public"
    if addr.is_loopback:
        return "loopback"
    if addr in ipaddress.ip_network("100.64.0.0/10"):
        return "cgnat"
    if addr.is_link_local:
        return "linklocal"
    return "private"


async def tls_certificate_ok(
    hostname: str, port: int = 443, timeout: float = 5.0
) -> tuple[bool, str]:
    """Can we complete a verified TLS handshake to this host?

    Uses the default verification context on purpose: a self-signed or
    mismatched certificate fails, which is the fail-closed behavior the
    wizard needs ("remote mode never activates over an unverifiable
    channel").
    """
    context = ssl.create_default_context()

    def _handshake() -> tuple[bool, str]:
        with socket.create_connection((hostname, port), timeout=timeout) as raw:
            raw.settimeout(timeout)
            with context.wrap_socket(
                raw, server_hostname=hostname
            ) as tls:
                cert = tls.getpeercert()
                not_after = (cert or {}).get("notAfter", "")
                return True, f"valid until {not_after}" if not_after else "valid"

    try:
        return await asyncio.to_thread(_handshake)
    except Exception as exc:
        return False, str(exc)[:200]


async def http_reachable(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    """Does this URL answer at all? Any HTTP status means the path works."""
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True
        ) as client:
            response = await client.get(url)
        return response.status_code < 500, f"HTTP {response.status_code}"
    except Exception as exc:
        return False, str(exc)[:200]
