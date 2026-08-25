"""Alerts that know why they fired (issue #149).

An established :class:`EntityAssociation` is a claim about habit: this
person leaves in that car, on weekday mornings, from that camera. Once a
habit is written down, the interesting event is not "a vehicle appeared"
but "this is not the vehicle that is normally here at this hour". The
rule vocabulary could only express the first, which is why unknown-vehicle
alerts are noisy: they carry no reason.

Four deviations, all read off the edge rather than a model:

``unexpected_object``
    A different object is where an established edge's object usually is,
    at an hour that edge is usually active. The parked-in-your-spot case.
``wrong_time``
    The expected pairing happened, but at an hour with no history.
``expected_absent``
    The pairing usually happens by now on a day like today, and has not.
``unauthorized``
    A learned ``uses`` edge exists where policy requires a declared
    ``authorized_for`` edge and there is none. The warehouse case.

The first three are habit. The last is policy, and the difference is
load-bearing: habit is inferred and can be wrong, policy is asserted by an
administrator and is not up for inference. They share a mechanism and
nothing else.

Everything here is pure. The caller supplies the edges and the clock, and
emits whatever comes back. That keeps the reasoning testable without a
database, and keeps the alerting decision separate from the plumbing that
delivers it.
"""

from __future__ import annotations

import logging
from datetime import datetime

from services.perception.associator import local_buckets

logger = logging.getLogger("nurby.perception.deviations")


# An hour counts as "usual" for an edge once it holds at least this share
# of the edge's observations. Low, because a habit spread across 07:00 and
# 08:00 should count both, and a stricter gate would make a person who
# leaves anywhere in a two-hour window look like they have no pattern.
USUAL_HOUR_MIN_SHARE = 0.15

# How far past the usual hour to wait before calling something absent.
# A habit is not a timetable; someone leaving an hour late is not news.
ABSENCE_GRACE_HOURS = 2

# Deviations are only computed for edges the household has actually
# established. A candidate edge is a coincidence that has not proved
# itself, and alerting on one would be alerting on noise.
ALERTABLE_STATUSES = {"established"}


# ---- reading an edge -----------------------------------------------------


def _total(histogram: dict | None) -> int:
    return sum(int(v) for v in (histogram or {}).values())


def usual_hours(edge, min_share: float = USUAL_HOUR_MIN_SHARE) -> set[int]:
    """Hours this edge is normally active in, household-local. Pure."""
    hist = edge.hour_histogram or {}
    total = _total(hist)
    if total <= 0:
        return set()
    return {
        int(hour)
        for hour, count in hist.items()
        if int(count) / total >= min_share
    }


def usual_cameras(edge, min_share: float = USUAL_HOUR_MIN_SHARE) -> set[str]:
    """Cameras this edge is normally seen on. Pure."""
    hist = edge.camera_histogram or {}
    total = _total(hist)
    if total <= 0:
        return set()
    return {
        str(cam)
        for cam, count in hist.items()
        if int(count) / total >= min_share
    }


def is_alertable(edge) -> bool:
    """Whether an edge is settled enough to reason about. Pure."""
    if edge is None:
        return False
    if getattr(edge, "status", None) not in ALERTABLE_STATUSES:
        return False
    # A rejected or archived edge never reaches here, and a declared edge
    # is policy rather than habit: it has no histograms to deviate from.
    return getattr(edge, "source", "learned") == "learned"


# ---- the four detectors --------------------------------------------------


def detect_unexpected_object(
    edge, *, present_object_key: str, camera_id: str, when: datetime, tz_name: str
) -> dict | None:
    """Something else is where this edge's object usually is, now.

    Returns an event payload, or None when this is not a deviation. The
    caller is responsible for having established that ``present_object_key``
    is genuinely present; this decides only whether that is surprising.
    Pure, for tests.
    """
    if not is_alertable(edge):
        return None
    if str(present_object_key) == str(edge.object_key):
        return None  # the usual object. not news.
    cams = usual_cameras(edge)
    if cams and str(camera_id) not in cams:
        return None  # not the place this habit happens
    _, hour, _ = local_buckets(when, tz_name)
    if hour not in usual_hours(edge):
        return None  # not the time either. no expectation to violate
    return {
        "deviation": "unexpected_object",
        "subject_kind": edge.subject_kind,
        "subject_key": edge.subject_key,
        "relation": edge.relation,
        "expected_object_key": edge.object_key,
        "expected_object_label": edge.object_label,
        "present_object_key": str(present_object_key),
        "camera_id": str(camera_id),
        "hour": hour,
        "reason": (
            f"{edge.object_label or edge.object_key} is normally here around "
            f"{hour:02d}:00, but something else is"
        ),
    }


def detect_wrong_time(edge, *, camera_id: str, when: datetime, tz_name: str) -> dict | None:
    """The expected pairing happened at an hour it never happens. Pure."""
    if not is_alertable(edge):
        return None
    hours = usual_hours(edge)
    if not hours:
        return None
    _, hour, _ = local_buckets(when, tz_name)
    if hour in hours:
        return None
    # Adjacent hours are not a deviation. A habit is not a timetable.
    if any(abs(hour - h) <= 1 or abs(hour - h) == 23 for h in hours):
        return None
    return {
        "deviation": "wrong_time",
        "subject_kind": edge.subject_kind,
        "subject_key": edge.subject_key,
        "relation": edge.relation,
        "object_key": edge.object_key,
        "object_label": edge.object_label,
        "camera_id": str(camera_id) if camera_id else None,
        "hour": hour,
        "usual_hours": sorted(hours),
        "reason": (
            f"{edge.subject_key} and {edge.object_label or edge.object_key} "
            f"normally happen around {min(hours):02d}:00, not {hour:02d}:00"
        ),
    }


def detect_expected_absent(edge, *, now: datetime, tz_name: str) -> dict | None:
    """A habit that should have happened by now on a day like today.

    Only fires on a weekday pattern the edge actually has: an edge seen
    only on Saturdays says nothing about a Tuesday. Pure, for tests.
    """
    if not is_alertable(edge):
        return None
    hours = usual_hours(edge)
    if not hours:
        return None
    day_key, hour, weekday = local_buckets(now, tz_name)
    if edge.last_day == day_key:
        return None  # already happened today
    dow = edge.dow_histogram or {}
    dow_total = _total(dow)
    if dow_total <= 0 or int(dow.get(str(weekday), 0)) <= 0:
        return None  # no expectation for a day like this one
    latest = max(hours)
    if hour < latest + ABSENCE_GRACE_HOURS:
        return None  # still inside the grace window
    return {
        "deviation": "expected_absent",
        "subject_kind": edge.subject_kind,
        "subject_key": edge.subject_key,
        "relation": edge.relation,
        "object_key": edge.object_key,
        "object_label": edge.object_label,
        "usual_hours": sorted(hours),
        "hour": hour,
        "reason": (
            f"{edge.subject_key} normally uses "
            f"{edge.object_label or edge.object_key} by {latest:02d}:00 on a "
            "day like today, and has not"
        ),
    }


def detect_unauthorized(learned_edge, declared_edges) -> dict | None:
    """Use of a controlled object by someone not declared for it.

    ``declared_edges`` is every ``authorized_for`` edge for the same
    object. An object with none is not access-controlled and is nobody's
    violation: the absence of a policy is not a policy. Pure, for tests.
    """
    if learned_edge is None or learned_edge.relation != "uses":
        return None
    if getattr(learned_edge, "source", "learned") != "learned":
        return None
    controlled = [
        e for e in (declared_edges or [])
        if e.relation == "authorized_for"
        and e.source == "declared"
        and str(e.object_key) == str(learned_edge.object_key)
    ]
    if not controlled:
        return None
    for e in controlled:
        if (
            e.subject_kind == learned_edge.subject_kind
            and str(e.subject_key) == str(learned_edge.subject_key)
        ):
            return None  # declared for it
    return {
        "deviation": "unauthorized",
        "subject_kind": learned_edge.subject_kind,
        "subject_key": learned_edge.subject_key,
        "relation": "uses",
        "object_key": learned_edge.object_key,
        "object_label": learned_edge.object_label,
        "authorized_subjects": sorted(str(e.subject_key) for e in controlled),
        "reason": (
            f"{learned_edge.subject_key} used "
            f"{learned_edge.object_label or learned_edge.object_key}, which is "
            "restricted to declared operators"
        ),
    }


# ---- emission ------------------------------------------------------------


# Wired by the perception service to the shared RuleEngine, exactly as the
# incident tracker does, so this module stays importable without the engine.
_rule_event_sink = None


def set_rule_event_sink(sink) -> None:
    global _rule_event_sink
    _rule_event_sink = sink


async def emit(payload: dict) -> None:
    """Publish one deviation as a rule event. Never raises."""
    if _rule_event_sink is None or not payload:
        return
    body = dict(payload)
    body["event_kind"] = "association"
    try:
        await _rule_event_sink(body)
    except Exception:
        logger.exception("deviation rule-event sink failed")
