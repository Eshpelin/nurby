"""Household-wide pause for new work (issue #139).

There was a per-run ``AgentDriver.stop()`` and nothing above it. A
misconfigured model or a rule firing in a loop could only be stopped by
restarting the API, which also drops every in-flight request that had
nothing to do with the problem.

This is a sentinel file, checked with a single ``os.stat``. Three
properties matter and all three are deliberate:

**It pauses new work only.** Nothing in flight is killed. A run that has
already spent money on tool calls finishes and gives its answer. This is
pause, not panic: the recovery path is to stop making the problem worse,
not to throw away work already done.

**The check is cheap enough to run every time.** One stat call, no
caching beyond what the OS does, so engaging or disengaging takes effect
on the very next check rather than after a cache expiry.

**A corrupt or empty sentinel still counts as engaged.** Someone typing
``touch`` on the path, or a half-written file, means the household wanted
things stopped. Failing open because the JSON did not parse would be the
worst possible reading of that.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("nurby.estop")

# Overridable so tests never touch a real path, and so a deployment can
# put it on a volume that survives a container restart.
ESTOP_PATH_ENV = "NURBY_ESTOP_PATH"
DEFAULT_ESTOP_PATH = "/var/lib/nurby/ESTOP"


def estop_path() -> str:
    return os.environ.get(ESTOP_PATH_ENV) or DEFAULT_ESTOP_PATH


def is_engaged() -> bool:
    """Whether new work is paused. One stat call. Never raises."""
    try:
        return os.path.exists(estop_path())
    except OSError:
        # Cannot tell. Say no: a filesystem error must not silently
        # freeze a household that never asked for a pause.
        logger.debug("estop check failed", exc_info=True)
        return False


def reason() -> str | None:
    """Why it was engaged, when that was recorded.

    A missing, empty, or malformed body is not an error: the pause holds
    regardless, and this only supplies a nicer message when it can.
    """
    if not is_engaged():
        return None
    try:
        with open(estop_path(), encoding="utf-8") as handle:
            body = json.load(handle)
        value = body.get("reason")
        return str(value) if value else None
    except (OSError, ValueError, AttributeError):
        return None


def engage(why: str | None = None) -> None:
    """Pause new work. Idempotent."""
    path = estop_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "reason": why,
        "engaged_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    logger.warning("ESTOP engaged: %s", why or "no reason given")


def disengage() -> None:
    """Resume. Idempotent: removing an absent sentinel is fine."""
    try:
        os.remove(estop_path())
        logger.warning("ESTOP released")
    except FileNotFoundError:
        pass
