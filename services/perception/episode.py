"""Episode context: where a frame sits in the story already being told.

The temporal lens montages `[prev, current, next]` from an overlapping
recording, which is seconds of memory. Meanwhile the pipeline has already
grouped the frame into an Incident (this camera, this signature, still open)
and possibly a Journey (the same subject across cameras), and the lens never
saw either (issue #130).

This module renders that grouping as a short context block. Query-only and
deterministic, like `baseline.py`: no VLM call, no new table. Where the
baseline answers "is this normal for this camera", this answers "what has been
happening in the minutes before this frame".
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from shared.models import Incident, Journey, Observation

logger = logging.getLogger("nurby.perception.episode")

# How many earlier captions from the same incident to replay. Two is enough
# to establish how the episode opened without crowding out the frames.
MAX_EARLIER_CAPTIONS = 2
MAX_CAPTION_CHARS = 140
MAX_JOURNEY_STOPS = 4


def _minutes_between(later: datetime, earlier: datetime) -> int:
    delta = later.astimezone(timezone.utc) - earlier.astimezone(timezone.utc)
    return max(0, int(delta.total_seconds() // 60))


def _clip(text: str | None) -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    if len(text) > MAX_CAPTION_CHARS:
        return text[: MAX_CAPTION_CHARS - 3].rstrip() + "..."
    return text


def format_episode_context(incident: dict | None, earlier_captions: list[str],
                           journey: dict | None) -> str | None:
    """Render the episode block for the temporal lens.

    ``incident`` is ``{"minutes_open": int, "occurrence_count": int,
    "summary": str | None}``; ``journey`` is ``{"stops": [(camera_name,
    minutes_ago)], "subject": str | None}``. Returns None when there is
    nothing to say, so the caller sends no block at all. Pure, for tests."""
    lines: list[str] = []

    if incident:
        opened = incident.get("minutes_open") or 0
        count = incident.get("occurrence_count") or 0
        when = "just now" if opened < 1 else f"{opened} minute{'s' if opened != 1 else ''} ago"
        lines.append(
            f"THIS FRAME CONTINUES AN EPISODE already in progress on this "
            f"camera. It began {when} and this is sighting {count} in it."
        )
        summary = _clip(incident.get("summary"))
        if summary:
            lines.append(f"  So far: {summary}")
        for caption in earlier_captions[:MAX_EARLIER_CAPTIONS]:
            clipped = _clip(caption)
            if clipped:
                lines.append(f"  Earlier in the episode: {clipped}")

    if journey and journey.get("stops"):
        stops = []
        for camera_name, minutes_ago in journey["stops"][:MAX_JOURNEY_STOPS]:
            ago = "just now" if minutes_ago < 1 else f"{minutes_ago} min ago"
            stops.append(f"{camera_name} ({ago})")
        subject = journey.get("subject")
        who = f"The same {subject}" if subject else "The same subject"
        lines.append(f"{who} was seen on: " + ", ".join(stops) + ".")

    if not lines:
        return None
    lines.append(
        "Describe what is happening NOW in these frames and how it continues "
        "that. Do not repeat the earlier text back to me, and do not assume "
        "anything the frames do not show."
    )
    return "\n".join(lines)


async def episode_context(db, obs_id, camera_id, ts) -> str | None:
    """The episode block for one observation, or None when it stands alone.

    Never raises: losing this context must not cost the caller its lens."""
    try:
        obs = await db.get(Observation, obs_id)
        if obs is None or obs.incident_id is None:
            return None
        inc = await db.get(Incident, obs.incident_id)
        if inc is None:
            return None

        incident = {
            "minutes_open": _minutes_between(ts, inc.started_at),
            "occurrence_count": inc.occurrence_count,
            "summary": inc.summary_text,
        }

        # Earlier captions from the same incident, oldest first, excluding
        # this frame. Bounded by MAX_EARLIER_CAPTIONS.
        rows = (await db.execute(
            select(Observation.vlm_description)
            .where(Observation.incident_id == inc.id)
            .where(Observation.id != obs_id)
            .where(Observation.started_at < ts)
            .where(Observation.vlm_description.is_not(None))
            .order_by(Observation.started_at.asc())
            .limit(MAX_EARLIER_CAPTIONS)
        )).all()
        earlier = [r[0] for r in rows]

        journey = None
        if inc.journey_id is not None:
            jrn = await db.get(Journey, inc.journey_id)
            if jrn is not None:
                stops = []
                for seg in (jrn.segments or []):
                    if not isinstance(seg, dict):
                        continue
                    name = seg.get("camera_name")
                    seen_raw = seg.get("last_seen_at") or seg.get("started_at")
                    if not name or not seen_raw:
                        continue
                    if str(seg.get("camera_id")) == str(camera_id):
                        continue  # where we already are
                    try:
                        seen = datetime.fromisoformat(str(seen_raw))
                    except ValueError:
                        continue
                    stops.append((name, _minutes_between(ts, seen)))
                stops.sort(key=lambda s: s[1])
                if stops:
                    journey = {
                        "stops": stops,
                        "subject": jrn.subject_key if jrn.subject_kind == "person" else None,
                    }

        return format_episode_context(incident, earlier, journey)
    except Exception:
        logger.debug("episode context failed for observation %s", obs_id, exc_info=True)
        return None
