"""Remote access: state, connectivity brain, and phone-assisted probe (#183).

Backend for Settings → Remote access. The design contract (see
docs/remote-access-design.md): one HTTPS ingress, opt-in activation, and
fail closed — the wizard only reports "verified" when the domain resolves
here, TLS validates, health answers, AND a probe request provably arrived
from a public (non-LAN) source address over HTTPS.

The only new network surface is the probe echo endpoint. It answers one
JSON object, requires no authentication (the phone scanning the QR is not
logged in), records nothing but the fact that a public source hit the
nonce, and refuses to verify over plain HTTP or from private addresses.
"""

import asyncio
import re
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from services.api import remote_connectivity
from shared import app_settings
from shared.auth import require_admin
from shared.config import settings
from shared.database import get_db
from shared.models import User

router = APIRouter()

_PROBE_TTL_SECONDS = 600
_PROBE_RATE_LIMIT = 30  # hits per window per source IP
_PROBE_RATE_WINDOW = 300.0

# nonce -> {"created": monotonic, "verified": bool, "source": str | None}
_probes: dict[str, dict] = {}
_probe_rate: dict[str, tuple[float, int]] = {}

# Hostname: dot-separated labels, letters/digits/hyphens. At least one dot
# because ACME needs a public suffix to issue for; a single-label name can
# never complete the wizard's TLS gate anyway.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}\.?$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z]{2,63}$",
    re.IGNORECASE,
)


class DomainBody(BaseModel):
    domain: str


class ProbeResponse(BaseModel):
    status: str  # verified | waiting | insecure | unknown | rate_limited
    detail: str | None = None


class ProbeState(BaseModel):
    nonce: str
    url: str
    created_at: float
    expires_at: float
    verified: bool
    verified_from: str | None


class ConnectivityReport(BaseModel):
    public_ip: str | None = None
    domain_addresses: list[str] = []
    dns_matches_public_ip: bool | None = None
    tls_ok: bool | None = None
    tls_detail: str | None = None
    health_ok: bool | None = None
    health_detail: str | None = None
    ingress_caddy: bool = False


class RemoteAccessState(BaseModel):
    configured: bool
    domain: str | None = None
    scheme: str | None = None
    public_base_url: str | None = None
    connectivity: ConnectivityReport | None = None
    probe: ProbeState | None = None


async def configured_public_url() -> tuple[str | None, str | None]:
    """(scheme, host) of the effective public base URL, or (None, None).

    Mirrors the settings surface: a value saved through the wizard wins
    over the PUBLIC_BASE_URL environment fallback.
    """
    raw = (await app_settings.get_setting("public_base_url", None)) or (
        settings.public_base_url or ""
    )
    raw = str(raw).strip().rstrip("/")
    if not raw:
        return None, None
    from urllib.parse import urlparse

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None, None
    return parsed.scheme, parsed.hostname


async def _caddy_detected() -> bool:
    """Is the bundled ingress container on our compose network?"""
    import socket as _socket

    def _resolve() -> bool:
        try:
            _socket.gethostbyname("caddy")
            return True
        except Exception:
            return False

    return await asyncio.to_thread(_resolve)


def _new_probe(domain: str) -> ProbeState:
    nonce = secrets.token_urlsafe(16)
    now = time.monotonic()
    _probes[nonce] = {"created": now, "verified": False, "source": None}
    _prune_probes(now)
    return ProbeState(
        nonce=nonce,
        url=f"https://{domain}/api/system/remote-access/probe/{nonce}",
        created_at=now,
        expires_at=now + _PROBE_TTL_SECONDS,
        verified=False,
        verified_from=None,
    )


def _prune_probes(now: float) -> None:
    for nonce in [n for n, p in _probes.items() if now - p["created"] > _PROBE_TTL_SECONDS]:
        _probes.pop(nonce, None)


def _active_probe() -> ProbeState | None:
    now = time.monotonic()
    _prune_probes(now)
    for nonce, probe in _probes.items():
        if now - probe["created"] <= _PROBE_TTL_SECONDS:
            return ProbeState(
                nonce=nonce,
                url="",
                created_at=probe["created"],
                expires_at=probe["created"] + _PROBE_TTL_SECONDS,
                verified=probe["verified"],
                verified_from=probe["source"],
            )
    return None


def register_probe_hit(nonce: str, source_ip: str, scheme: str) -> str:
    """The fail-closed heart of the probe: only a public source over HTTPS
    can flip a probe to verified. Returns the resulting status word."""
    now = time.monotonic()
    _prune_probes(now)
    probe = _probes.get(nonce)
    if probe is None or now - probe["created"] > _PROBE_TTL_SECONDS:
        return "unknown"
    if probe["verified"]:
        return "verified"
    if scheme != "https":
        return "insecure"
    if remote_connectivity.classify_ip(source_ip) != "public":
        return "waiting"
    probe["verified"] = True
    probe["source"] = source_ip
    return "verified"


def _probe_rate_ok(source_ip: str, now: float) -> bool:
    window_start, count = _probe_rate.get(source_ip, (now, 0))
    if now - window_start > _PROBE_RATE_WINDOW:
        window_start, count = now, 0
    count += 1
    _probe_rate[source_ip] = (window_start, count)
    return count <= _PROBE_RATE_LIMIT


async def _connectivity_report(domain: str, scheme: str) -> ConnectivityReport:
    """Run every connectivity check concurrently; individual failures
    degrade their own field instead of failing the report."""
    stun, dns, tls, health, caddy = await asyncio.gather(
        remote_connectivity.stun_public_ip(),
        remote_connectivity.resolve_domain_ips(domain),
        (
            remote_connectivity.tls_certificate_ok(domain)
            if scheme == "https"
            else _noop_tls()
        ),
        remote_connectivity.http_reachable(f"{scheme}://{domain}/api/health"),
        _caddy_detected(),
        return_exceptions=True,
    )

    public_ip = stun if isinstance(stun, str) else None
    addresses = dns if isinstance(dns, list) else []
    tls_ok, tls_detail = tls if isinstance(tls, tuple) else (None, None)
    health_ok, health_detail = health if isinstance(health, tuple) else (None, None)

    return ConnectivityReport(
        public_ip=public_ip,
        domain_addresses=addresses,
        dns_matches_public_ip=(
            bool(public_ip) and public_ip in addresses if public_ip else None
        ),
        tls_ok=tls_ok,
        tls_detail=tls_detail,
        health_ok=health_ok,
        health_detail=health_detail,
        ingress_caddy=bool(caddy),
    )


async def _noop_tls() -> tuple[bool | None, str | None]:
    return None, "not applicable over plain HTTP"


@router.get("/system/remote-access", response_model=RemoteAccessState)
async def get_remote_access_state(
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    scheme, host = await configured_public_url()
    del db
    if not host:
        return RemoteAccessState(configured=False)
    report = await _connectivity_report(host, scheme or "https")
    return RemoteAccessState(
        configured=True,
        domain=host,
        scheme=scheme,
        public_base_url=f"{scheme}://{host}",
        connectivity=report,
        probe=_active_probe(),
    )


@router.put("/system/remote-access/domain", response_model=RemoteAccessState)
async def set_remote_access_domain(
    body: DomainBody,
    _current_user: User = Depends(require_admin),
):
    domain = (body.domain or "").strip().lower().rstrip(".")
    if "://" in domain or "/" in domain or " " in domain:
        raise HTTPException(status_code=400, detail="Enter just the hostname, e.g. camera.example.com")
    if not _HOSTNAME_RE.match(domain):
        raise HTTPException(
            status_code=400,
            detail="That does not look like a public domain name (e.g. camera.example.com).",
        )
    # Remote mode is HTTPS-only: store the https URL so share links,
    # webhooks, and pairing payloads can never advertise plain HTTP.
    await app_settings.set_setting("public_base_url", f"https://{domain}")
    report = await _connectivity_report(domain, "https")
    return RemoteAccessState(
        configured=True,
        domain=domain,
        scheme="https",
        public_base_url=f"https://{domain}",
        connectivity=report,
        probe=_active_probe(),
    )


@router.delete("/system/remote-access/domain", response_model=RemoteAccessState)
async def clear_remote_access_domain(
    _current_user: User = Depends(require_admin),
):
    """Opt-out path: remote access is opt-in, so disabling must be one call."""
    current = await app_settings.get_setting("public_base_url", None)
    if current:
        await app_settings.set_setting("public_base_url", None)
    _probes.clear()
    return RemoteAccessState(configured=False)


@router.post("/system/remote-access/probe", response_model=ProbeState)
async def start_probe(_current_user: User = Depends(require_admin)):
    scheme, host = await configured_public_url()
    if not host or scheme != "https":
        raise HTTPException(
            status_code=400,
            detail="Set a domain first; the probe runs against the public HTTPS URL.",
        )
    return _new_probe(host)


@router.get("/system/remote-access/probe", response_model=ProbeState | None)
async def probe_status(_current_user: User = Depends(require_admin)):
    return _active_probe()


@router.get(
    "/system/remote-access/probe/{nonce}",
    response_model=ProbeResponse,
)
async def probe_hit(nonce: str, request: Request):
    """Public echo endpoint: the phone on cellular lands here.

    Marks the probe verified only when the hit provably came from a
    public source address over HTTPS — a scan on the home wifi reads as
    "waiting", which is exactly the instruction the wizard gives.
    """
    source = request.client.host if request.client else ""
    now = time.monotonic()
    if not _probe_rate_ok(source, now):
        return ProbeResponse(status="rate_limited", detail="Too many probe requests")
    status = register_probe_hit(nonce, source, request.url.scheme)
    detail = {
        "waiting": "Received, but from a private address. Open this link on cellular data (turn wifi off).",
        "insecure": "Reached over plain HTTP; verification requires HTTPS.",
    }.get(status)
    return ProbeResponse(status=status, detail=detail)
