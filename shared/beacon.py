"""End-to-end 'system alive' beacon for an external dead-man's switch (#211).

Nurby's own alert channels (Telegram, email, push) all send *from* the box
that runs the stack. If the host loses power, the network drops, or Docker
dies, no alert can be sent, and from the user's side that silence is
indistinguishable from a genuinely quiet home. For the away-from-home
persona this is the single scenario the product is bought for.

The fix is an *external* watchdog that polls this beacon on a schedule and
alerts through an off-box channel when the beacon stops answering. This
module computes the beacon Nurby exposes. It reflects real end-to-end
monitoring capability, not just "the API process is up":

* **database** - the API can read its own store.
* **ingestion** - the worker pulling frames is beating.
* **perception** - the worker turning frames into observations is beating.
* **observation_writer** - the pipeline is actually producing, not silently
  failing every write while the worker still beats.

Liveness is read from the very same heartbeat / component-health keys the
doctor inspects (``shared.heartbeat`` + ``shared.component_health``), so
there is exactly one source of truth. A dead worker's key expires after
``heartbeat.TTL_SECONDS``; that TTL is reported to the caller so the recipe
can state its detection window honestly.

The endpoint that serves this is unauthenticated on purpose (an external
cron cannot hold a session) and returns only coarse booleans, never
camera-scoped data.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from shared import component_health, heartbeat
from shared.clock import stamp_now

# Components whose failure means "the home is effectively unmonitored".
# API liveness is implicit: if this code runs, the API answered.
CRITICAL = ("database", "ingestion", "perception", "observation_writer")


async def _database_ok(db: AsyncSession) -> bool:
    try:
        await db.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def compute_beacon(db: AsyncSession) -> tuple[dict, bool]:
    """Return ``(payload, healthy)``.

    ``healthy`` is True only when every :data:`CRITICAL` capability is
    confirmed working. Anything unconfirmed (a dead worker, an unreachable
    Redis so liveness cannot be read, a failing writer) makes the beacon
    degraded so the external watchdog trips. Fail-closed by construction:
    the honest answer while we cannot confirm monitoring is "degraded".
    """
    database = await _database_ok(db)
    ingestion = await heartbeat.is_alive(heartbeat.INGESTION)
    perception = await heartbeat.is_alive(heartbeat.PERCEPTION)

    # The writer publishes ok/fail with a TTL; absence (None) reads as
    # "unknown", which we treat as not-confirmed-ok and therefore degraded,
    # matching the fail-closed posture of the rest of the beacon.
    writer_health = await component_health.get(component_health.OBSERVATION_WRITER)
    writer_status = (writer_health or {}).get("status")
    observation_writer = writer_status == component_health.OK

    checks = {
        "api": True,
        "database": database,
        "ingestion": ingestion,
        "perception": perception,
        "observation_writer": observation_writer,
    }
    failing = [name for name in CRITICAL if not checks[name]]
    healthy = not failing

    payload = {
        "beacon": "alive" if healthy else "degraded",
        "healthy": healthy,
        "checks": checks,
        "failing": failing,
        # How long a just-died worker can still read as alive before its
        # heartbeat key expires. The external watchdog must poll at least
        # this often, and its own honest detection window is roughly its
        # poll interval plus this value.
        "stale_after_seconds": heartbeat.TTL_SECONDS,
        "generated_at": stamp_now().isoformat(),
    }
    return payload, healthy
