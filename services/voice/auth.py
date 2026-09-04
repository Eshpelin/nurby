"""HTTP and RTSP digest authentication (issue #155).

Most IP cameras refuse Basic and answer with Digest, so a transport layer
that only speaks Basic works on a demo unit and fails on half the real
ones. httpx handles digest for HTTP, but the RTSP path is a hand-rolled
socket client and needs its own, and the vendor HTTP drivers want the
same challenge parsing, so it lives here once.

Deliberately only what cameras actually use: MD5 and MD5-sess, qop=auth
or absent. SHA-256 digest exists in RFC 7616 and no camera has been seen
asking for it; if one does, it will fail loudly here rather than silently
sending the wrong hash.
"""

from __future__ import annotations

import hashlib
import os
import re

_TOKEN = re.compile(r'(\w+)=(?:"([^"]*)"|([^,\s]+))')


def parse_challenge(header: str) -> dict:
    """Parse a ``WWW-Authenticate`` header into its parameters. Pure.

    Returns ``{}`` for a Basic-only or unparseable challenge, which
    callers read as "no digest available".
    """
    if not header or "digest" not in header.lower():
        return {}
    params = {}
    for match in _TOKEN.finditer(header):
        key = match.group(1).lower()
        params[key] = match.group(2) if match.group(2) is not None else match.group(3)
    return params


def _h(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def digest_response(
    *, username: str, password: str, method: str, uri: str,
    challenge: dict, cnonce: str | None = None, nc: int = 1,
) -> str | None:
    """Build an ``Authorization: Digest`` header value. Pure, for tests.

    Returns None when the challenge is missing what it needs, rather than
    constructing something that will be rejected.
    """
    realm = challenge.get("realm")
    nonce = challenge.get("nonce")
    if not realm or not nonce:
        return None

    algorithm = (challenge.get("algorithm") or "MD5").upper()
    if algorithm not in ("MD5", "MD5-SESS"):
        return None

    ha1 = _h(f"{username}:{realm}:{password}")
    cnonce = cnonce or os.urandom(8).hex()
    if algorithm == "MD5-SESS":
        ha1 = _h(f"{ha1}:{nonce}:{cnonce}")
    ha2 = _h(f"{method}:{uri}")

    qop = challenge.get("qop")
    if qop:
        # A server may offer several; auth is the only one cameras use,
        # and auth-int would require hashing the body we have not sent yet.
        qop = "auth" if "auth" in qop.split(",") else None

    if qop:
        nc_value = f"{nc:08x}"
        response = _h(f"{ha1}:{nonce}:{nc_value}:{cnonce}:{qop}:{ha2}")
        parts = [
            f'username="{username}"', f'realm="{realm}"', f'nonce="{nonce}"',
            f'uri="{uri}"', f"algorithm={algorithm}", f"qop={qop}",
            f"nc={nc_value}", f'cnonce="{cnonce}"', f'response="{response}"',
        ]
    else:
        response = _h(f"{ha1}:{nonce}:{ha2}")
        parts = [
            f'username="{username}"', f'realm="{realm}"', f'nonce="{nonce}"',
            f'uri="{uri}"', f"algorithm={algorithm}", f'response="{response}"',
        ]

    opaque = challenge.get("opaque")
    if opaque:
        parts.append(f'opaque="{opaque}"')
    return "Digest " + ", ".join(parts)


def basic_header(username: str, password: str) -> str:
    """An ``Authorization: Basic`` value. Pure, for tests."""
    import base64

    token = base64.b64encode(
        f"{username}:{password or ''}".encode("utf-8")
    ).decode("ascii")
    return f"Basic {token}"
