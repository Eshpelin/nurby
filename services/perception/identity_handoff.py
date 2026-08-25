"""Cross-camera identity hand-off, keyed by body cluster (issue #147).

``IdentityBinder`` holds a track's identity in memory, keyed by
``camera_id -> tracker_id``. That solves occlusion on one camera and
nothing else. A ``tracker_id`` is meaningless across cameras, so walking
from the hallway into the kitchen started from an empty binding and waited
for a fresh face, and a perception restart dropped every binding in the
house at once.

A body cluster is cross-camera by construction: that is what
``reid.BodyReID`` builds. So the hand-off is keyed on
``body_cluster_id -> {person_id, person_name}`` and lives in Redis, which
makes it survive a restart for free.

Two rules keep this from turning into a way for a wrong identity to live
forever:

1. **Only face evidence publishes.** A binding recovered from this map is
   never written back (see ``identity_binding.writes_for``). If lookups
   could refresh the TTL, an identity would keep itself alive indefinitely
   by being read, and the expiry below would never actually fire.
2. **The TTL is the hold, and it is short.** It matches the journey idle
   window, because the question this map answers is the same one a journey
   asks: is this plausibly the same visit?

Redis failures are swallowed. A missing hand-off costs continuity, which
is what we had before this module; raising here would cost the keyframe.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger("nurby.perception.identity_handoff")

# Matches JOURNEY_IDLE_SECONDS_DEFAULT. A hand-off older than the window
# that would have ended the journey is not the same visit, and should not
# be silently carried onto a new one.
DEFAULT_TTL_SECONDS = 300


def _key(body_cluster_id) -> str:
    return f"identity:body:{body_cluster_id}"


async def lookup(redis, body_cluster_ids) -> dict[str, dict]:
    """Resolve body cluster ids to held identities.

    Returns ``{body_cluster_id: {"person_id", "person_name"}}`` for the ids
    that have one. Ids with no entry are simply absent. Never raises: a
    lookup failure means no hand-off, not a dropped keyframe.
    """
    ids = [str(b) for b in (body_cluster_ids or []) if b]
    if not ids or redis is None:
        return {}
    out: dict[str, dict] = {}
    try:
        for bid in ids:
            raw = await redis.get(_key(bid))
            if not raw:
                continue
            payload = json.loads(
                raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
            )
            pid = payload.get("person_id")
            if not pid:
                continue
            out[bid] = {
                "person_id": str(pid),
                "person_name": payload.get("person_name"),
            }
    except Exception:
        logger.debug("identity hand-off lookup failed", exc_info=True)
        return {}
    return out


async def publish(redis, writes, ttl: int = DEFAULT_TTL_SECONDS) -> int:
    """Store face-derived identities so another camera can pick them up.

    ``writes`` is ``{body_cluster_id: {"person_id", "person_name"}}``, and
    the caller is responsible for only passing face-derived bindings. See
    the module docstring for why that matters. Returns how many entries
    were written, for tests and telemetry.
    """
    if not writes or redis is None:
        return 0
    written = 0
    try:
        for bid, ident in writes.items():
            pid = (ident or {}).get("person_id")
            if not pid:
                continue
            await redis.set(
                _key(bid),
                json.dumps(
                    {
                        "person_id": str(pid),
                        "person_name": ident.get("person_name"),
                    }
                ),
                ex=ttl,
            )
            written += 1
    except Exception:
        logger.debug("identity hand-off publish failed", exc_info=True)
    return written
