"""Intake path: reviewed alert (#195) -> golden case.

Acceptance criterion. "Incorrect reviewed alerts can be added to the
set without manual schema work." A maintainer reviewing alerts marks
one "incorrect" with a reason (``wrong_object`` / ``wrong_person`` /
``duplicate`` / ``timing``, per ``EventFeedbackCreate``). This turns
that alert + its feedback into a golden case dict that ``case_from_dict``
loads unchanged, so the set grows straight from real failures.

The mapping is deliberate.

- ``wrong_object`` / ``wrong_person``. The alert asserted an object or
  person that was not there. The mis-asserted label becomes a
  ``forbidden`` phrase; the event is treated as absent unless the
  reviewer supplies the correct label.
- ``duplicate``. A real event, but the alert double-fired. Event stays
  present; the corrected description (if any) drives ``must_include``.
- ``timing``. The event is real but the window was wrong; event stays
  present and the correct wording seeds ``must_include``.

Callers pass plain dicts (an observation row and the feedback row) so
this never imports the ORM. It returns a dict ready to ``json.dump`` or
feed straight to ``case_from_dict``.
"""

from __future__ import annotations

from typing import Any

from services.agent.eval.golden.schema import GoldenCase, case_from_dict

# Which reasons imply the alert's asserted content was itself wrong (so
# the asserted label becomes forbidden) vs. a real event mis-timed or
# repeated.
_CONTENT_WRONG_REASONS = {"wrong_object", "wrong_person"}


def alert_to_golden_case_dict(
    observation: dict[str, Any],
    feedback: dict[str, Any],
    *,
    correct_label: str | None = None,
) -> dict[str, Any]:
    """Build a golden-case dict from an incorrect reviewed alert.

    ``observation`` needs at least ``id`` and a text field
    (``caption`` / ``summary`` / ``description``). ``feedback`` matches
    ``EventFeedbackCreate`` (``rating``, ``reason``). ``correct_label``
    is the reviewer's optional ground-truth phrase.
    """
    rating = feedback.get("rating")
    if rating != "incorrect":
        raise ValueError(
            f"intake only accepts rating='incorrect' alerts; got {rating!r}"
        )
    reason = feedback.get("reason")

    asserted = str(
        observation.get("caption")
        or observation.get("summary")
        or observation.get("description")
        or ""
    ).strip()

    obs_id = observation.get("id") or observation.get("observation_id") or "unknown"
    footage_hash = (
        observation.get("footage_hash")
        or observation.get("clip_hash")
        or observation.get("recording_hash")
    )

    content_wrong = reason in _CONTENT_WRONG_REASONS
    forbidden: list[str] = []
    must_include: list[str] = []
    if content_wrong and asserted:
        # The alert's own words are the confident-wrong claim to catch.
        forbidden = [asserted]
    if correct_label:
        must_include = [correct_label]

    # For content-wrong with no corrected label, treat as "no event of
    # that kind": the fixed output should not repeat the wrong claim.
    event_present = not (content_wrong and not correct_label)

    scenario = _reason_to_scenario(reason)

    return {
        "id": f"intake_{reason or 'incorrect'}_{obs_id}",
        "kind": "caption",
        "scenario": scenario,
        "source": "alert_intake",
        "footage": {
            "hash": footage_hash,
            "source": f"observation:{obs_id}",
            "note": "footage not committed; hash-pinned from reviewed alert",
        },
        "input": {
            "observation_id": obs_id,
            "feedback_reason": reason,
            "asserted_caption": asserted,
        },
        "ground_truth": {
            "event_present": event_present,
            "must_include": must_include,
            "forbidden": forbidden,
            "reference": correct_label or "",
        },
        # No replay prediction yet: a live run fills this. Until then the
        # replay provider yields an empty caption, which flags the case
        # as unfixed rather than silently passing.
        "mock_prediction": {},
    }


def alert_to_golden_case(
    observation: dict[str, Any],
    feedback: dict[str, Any],
    *,
    correct_label: str | None = None,
) -> GoldenCase:
    """Same as :func:`alert_to_golden_case_dict`, returned parsed."""
    return case_from_dict(
        alert_to_golden_case_dict(
            observation, feedback, correct_label=correct_label
        )
    )


def _reason_to_scenario(reason: str | None) -> str:
    return {
        "wrong_object": "ambiguous_face",
        "wrong_person": "ambiguous_face",
        "duplicate": "delivery",
        "timing": "missing_recording",
    }.get(reason or "", "ambiguous_face")


__all__ = ["alert_to_golden_case", "alert_to_golden_case_dict"]
