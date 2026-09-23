"""Grow the golden set from real failures (#214 <- #195).

When a user marks a fired alert ``incorrect`` (``EventFeedback``, #195),
that is a real-world case the model got wrong: exactly what the golden set
should learn from. This module turns such a review into a draft
:class:`GoldenCase` with no manual schema work, so the intake is one call
(or one CLI subcommand) rather than hand-authoring JSON.

The draft is deliberately *incomplete*: it captures what we know
automatically (the footage reference, the family guess from the reason, the
fact that the asserted event was wrong) and leaves ``reference`` for a human
to fill with the correct description. It is written with ``source`` set to
``feedback:<event_id>`` so its provenance is obvious and duplicates are
detectable.

Kept dict-in / case-out so it is unit-testable without a live database; a
thin DB adapter (:func:`intake_incorrect_feedback`) is provided for the CLI.
"""

from __future__ import annotations

from typing import Any

from services.agent.eval.golden.schema import GoldenCase, GroundTruth, MediaRef, save_case

# Map an EventFeedback.reason (#195 closed vocab) to a scenario family guess.
# The human curator can correct it, but this gets the case filed in the right
# bucket automatically most of the time.
_REASON_TO_FAMILY = {
    "wrong_object": "delivery",
    "wrong_person": "ambiguous_face",
    "duplicate": "no_event",
    "timing": "no_event",
}


def case_from_feedback(fb: dict[str, Any]) -> GoldenCase:
    """Build a draft golden case from an ``incorrect`` feedback record.

    ``fb`` is a plain dict so this is DB-free and testable. Expected keys:
    ``event_id`` (str), optional ``reason``, ``camera_id``, ``clip_sha256``,
    ``clip_path``, ``asserted_caption`` (what the model said), and optional
    ``event_present`` (defaults to False: an ``incorrect`` alert usually
    means "you flagged something that was not really the event").
    """
    event_id = str(fb["event_id"])
    reason = fb.get("reason") or ""
    family = _REASON_TO_FAMILY.get(reason, "no_event")
    media = None
    if fb.get("clip_sha256"):
        media = MediaRef(
            sha256=str(fb["clip_sha256"]),
            path=fb.get("clip_path"),
            note=f"from incorrect alert {event_id}"
            + (f" (reason: {reason})" if reason else ""),
        )
    return GoldenCase(
        id=f"feedback-{event_id}",
        family=family,
        kind="caption",
        truth=GroundTruth(
            event_present=bool(fb.get("event_present", False)),
            reference="",  # a human fills the correct description
            must_not_include=[],
        ),
        media=media,
        prompt=fb.get("prompt"),
        recorded_output=fb.get("asserted_caption"),
        source=f"feedback:{event_id}",
    )


async def intake_incorrect_feedback(db, limit: int = 100) -> list[str]:
    """Pull recent ``incorrect`` EventFeedback rows and write draft golden
    cases for any not already present. Returns the case ids written.

    DB-touching, so kept out of the pure path above. Idempotent: a case
    whose ``<id>.json`` already exists is skipped, so re-running does not
    clobber a curator's edits.
    """
    from sqlalchemy import select

    from services.agent.eval.golden.schema import GOLDEN_DIR
    from shared.models import Event
    from shared.models.rules import EventFeedback

    rows = (
        await db.execute(
            select(EventFeedback)
            .where(EventFeedback.rating == "incorrect")
            .order_by(EventFeedback.updated_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    written: list[str] = []
    for fb in rows:
        event_id = str(fb.event_id)
        if (GOLDEN_DIR / f"feedback-{event_id}.json").exists():
            continue
        event = await db.get(Event, fb.event_id)
        # The alert text lives in Event.payload (no dedicated column); pull
        # the most description-like field so the draft carries what the model
        # actually said, for a curator to compare against the truth.
        asserted = None
        ep = getattr(event, "payload", None) or {}
        if isinstance(ep, dict):
            for key in ("message", "description", "vlm_description", "summary", "caption"):
                if ep.get(key):
                    asserted = str(ep[key])
                    break
        payload: dict[str, Any] = {
            "event_id": event_id,
            "reason": fb.reason,
            "asserted_caption": asserted,
            "camera_id": str(getattr(event, "camera_id", "") or "") or None,
        }
        case = case_from_feedback(payload)
        save_case(case)
        written.append(case.id)
    return written
