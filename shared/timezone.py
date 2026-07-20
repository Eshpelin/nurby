"""The installation's timezone.

Timestamps are stored in UTC everywhere. Everything user-facing should render
in the *installation's* timezone -- the one place the cameras actually are --
so an event reads as house time whether you are at home or looking from
another country. Without this the two halves disagreed: the backend formatted
digest sentences in the container's UTC while the browser rendered every other
timestamp in the viewer's local zone, so "2:37 pm" in a digest pointed at no
recording the user could find.

Resolution order:
1. the ``system_timezone`` setting, when set and valid (explicit override)
2. the process timezone, which docker compose seeds from the host via ``TZ``
3. UTC
"""

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger("nurby.timezone")

FALLBACK = "UTC"


def _valid(name: str | None) -> str | None:
    """Return ``name`` when it is a loadable IANA zone, else None."""
    if not name:
        return None
    try:
        ZoneInfo(name)
        return name
    except Exception:
        return None


def process_timezone_name() -> str:
    """The timezone this process runs in, as an IANA name where possible.

    Prefers ``TZ`` because the local tzinfo often reports only an abbreviation
    or offset ("+06"), which is not a zone the browser can format with.
    """
    from_env = _valid(os.environ.get("TZ"))
    if from_env:
        return from_env
    local = datetime.now().astimezone().tzinfo
    return _valid(getattr(local, "key", None)) or FALLBACK


async def effective_timezone_name() -> str:
    """The installation timezone: explicit setting, else the process zone."""
    try:
        from shared.app_settings import get_setting

        configured = _valid(await get_setting("system_timezone", None))
        if configured:
            return configured
    except Exception:
        logger.debug("system_timezone lookup failed", exc_info=True)
    return process_timezone_name()


async def effective_timezone() -> ZoneInfo:
    """``effective_timezone_name`` as a tzinfo, never raising."""
    try:
        return ZoneInfo(await effective_timezone_name())
    except Exception:
        return ZoneInfo(FALLBACK)
