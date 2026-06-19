"""Resolve the runtime grounding configuration.

Grounding deliberately does **not** live in the ``providers`` table (design
§2.1/§3.1): the active-provider selection there is unfiltered by kind, so a
grounding row would get picked as "the VLM" and silently break captions.
Instead the static deploy knobs live in ``shared.config.settings`` and the
runtime toggles in ``app_settings`` (UI-flippable), resolved here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GroundingBackend:
    """A resolved place to send grounding requests.

    ``error`` is set (and ``base_url``/``kind`` left empty) when grounding is
    misconfigured, e.g. backend=="remote" with no URL or an SSRF-refused URL.
    """

    base_url: str
    kind: str  # "local" | "remote"
    leaves_privacy_boundary: bool = False
    error: str | None = None


async def is_enabled() -> bool:
    """Whether the grounding subsystem is turned on (default off)."""
    from shared.app_settings import get_setting

    return bool(await get_setting("grounding_enabled", False))


async def resolve_backend() -> GroundingBackend:
    """Where to send grounding requests, honoring the runtime backend choice.

    Remote endpoints are operator-supplied and fetched server-side, so the URL
    is run through the same SSRF policy as webhooks before we trust it.
    """
    from shared.app_settings import get_setting
    from shared.config import settings

    kind = (await get_setting("grounding_backend", "local") or "local").strip().lower()

    if kind == "remote":
        url = (await get_setting("grounding_remote_url", None) or "").strip()
        if not url:
            return GroundingBackend(
                "", "remote",
                error="grounding_backend is 'remote' but grounding_remote_url is not set",
            )
        from shared.netpolicy import webhook_target_rejection

        rejection = await webhook_target_rejection(url)
        if rejection:
            return GroundingBackend("", "remote", error=f"remote grounding URL refused: {rejection}")
        return GroundingBackend(url.rstrip("/"), "remote", leaves_privacy_boundary=True)

    # Default: the bundled local microservice.
    return GroundingBackend(settings.grounding_service_url.rstrip("/"), "local")


async def resolve_mode(override: str | None = None) -> str:
    """The inference mode (fast | slow | hybrid) for a request."""
    if override:
        return override
    from shared.app_settings import get_setting

    return (await get_setting("grounding_mode", "hybrid") or "hybrid").strip().lower()
