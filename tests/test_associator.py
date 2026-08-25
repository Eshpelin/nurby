"""Learned entity associations (issue #148).

The product question behind this: "Ahmed always leaves in the Harrier
around 8am, so warn me when someone else is in that spot." That needs an
edge between two identities, evidence that it recurs across days, and a
time distribution. These tests pin the rules that decide when co-presence
becomes a fact, and the ones that stop it from becoming a wrong fact.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services.perception import associator as assoc_mod
from services.perception.associator import (
    ASSOCIABLE_SUBJECT_KINDS,
    bump,
    fold,
    journey_camera_ids,
    local_buckets,
    next_status,
    vehicles_in,
)


def _edge(**kw):
    base = dict(
        subject_kind="person",
        subject_key="Ahmed",
        object_kind="vehicle",
        object_key="v-1",
        object_label="Harrier",
        relation="uses",
        source="learned",
        status="candidate",
        user_confirmed=False,
        evidence_count=0,
        distinct_days=0,
        last_day=None,
        hour_histogram=None,
        dow_histogram=None,
        first_seen_at=None,
        last_seen_at=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _at(day, hour, minute=0):
    return datetime(2026, 8, day, hour, minute, tzinfo=timezone.utc)


# ---- distinct days, not sighting count -----------------------------------


def test_many_sightings_in_one_day_are_one_day():
    """A van idling beside someone for twenty keyframes is one event. If
    evidence_count drove promotion, one morning would mint a fact."""
    e = _edge()
    for minute in range(0, 60, 3):
        fold(e, _at(1, 8, minute), "UTC", min_days=3)

    assert e.evidence_count == 20
    assert e.distinct_days == 1
    assert e.status == "candidate"


def test_promotion_needs_days():
    e = _edge()
    fold(e, _at(1, 8), "UTC", min_days=3)
    assert e.status == "candidate"
    fold(e, _at(2, 8), "UTC", min_days=3)
    assert e.status == "candidate"
    fold(e, _at(3, 8), "UTC", min_days=3)
    assert e.status == "established"
    assert e.distinct_days == 3


def test_day_boundary_uses_household_time_not_utc():
    """23:30 in Dhaka on the 2nd is 17:30 UTC on the 2nd, but 01:00 Dhaka
    on the 3rd is 19:00 UTC on the 2nd. Same UTC day, two local days."""
    e = _edge()
    fold(e, datetime(2026, 8, 2, 17, 30, tzinfo=timezone.utc), "Asia/Dhaka", 3)
    fold(e, datetime(2026, 8, 2, 19, 0, tzinfo=timezone.utc), "Asia/Dhaka", 3)

    assert e.distinct_days == 2


# ---- time distribution ---------------------------------------------------


def test_hour_histogram_is_local():
    e = _edge()
    # 02:00 UTC is 08:00 in Dhaka (UTC+6).
    fold(e, datetime(2026, 8, 1, 2, 0, tzinfo=timezone.utc), "Asia/Dhaka", 3)

    assert e.hour_histogram == {"8": 1}


def test_histograms_accumulate():
    e = _edge()
    fold(e, _at(1, 8), "UTC", 3)
    fold(e, _at(2, 8), "UTC", 3)
    fold(e, _at(3, 9), "UTC", 3)

    assert e.hour_histogram == {"8": 2, "9": 1}
    # 2026-08-01 is a Saturday.
    assert sum(e.dow_histogram.values()) == 3


def test_first_and_last_seen_track_the_span():
    e = _edge()
    fold(e, _at(5, 8), "UTC", 3)
    fold(e, _at(1, 8), "UTC", 3)
    fold(e, _at(9, 8), "UTC", 3)

    assert e.first_seen_at == _at(1, 8)
    assert e.last_seen_at == _at(9, 8)


# ---- rejection is permanent ---------------------------------------------


def test_a_rejected_edge_refuses_evidence():
    e = _edge(status="rejected", distinct_days=2)
    assert fold(e, _at(1, 8), "UTC", min_days=1) is False
    assert e.evidence_count == 0
    assert e.status == "rejected"


def test_a_rejected_edge_cannot_be_promoted_by_the_status_rule():
    assert next_status("rejected", 99, 3, user_confirmed=False) == "rejected"
    assert next_status("rejected", 99, 3, user_confirmed=True) == "rejected"


# ---- the user outranks the evidence -------------------------------------

def test_user_confirmation_holds_an_edge_established():
    """A pattern that thins out does not un-confirm what a person said is
    true."""
    assert next_status("established", 0, 3, user_confirmed=True) == "established"


def test_an_archived_edge_returns_as_a_candidate_not_established():
    assert next_status("archived", 1, 3, user_confirmed=False) == "candidate"


# ---- helpers -------------------------------------------------------------


def test_local_buckets_falls_back_to_utc_on_a_bad_timezone():
    day, hour, dow = local_buckets(_at(1, 8), "Not/AZone")
    assert (day, hour) == ("2026-08-01", 8)
    assert dow == 5  # Saturday


def test_local_buckets_assumes_utc_for_naive_datetimes():
    day, hour, _ = local_buckets(datetime(2026, 8, 1, 8, 0), "UTC")
    assert (day, hour) == ("2026-08-01", 8)


def test_bump_ignores_out_of_range_slots():
    assert bump({}, 24, 24) == {}
    assert bump({}, -1, 24) == {}
    assert bump(None, 0, 24) == {"0": 1}


def test_vehicles_in_ignores_unidentified_detections():
    """A box around something car-shaped is not an identity."""
    rows = [
        SimpleNamespace(camera_id=None, vehicle_detections={"vehicles": [
            {"vehicle_id": None, "identity_key": None},
            {"vehicle_id": "v-1", "identity_key": "ABC123"},
        ]}),
        SimpleNamespace(vehicle_detections={"vehicles": [
            {"vehicle_id": "v-1", "identity_key": "ABC123"},
        ]}),
        SimpleNamespace(vehicle_detections=None),
    ]
    assert vehicles_in(rows) == {
        "v-1": {"label": "ABC123", "camera_id": None}
    }


def test_journey_camera_ids_dedupes_and_skips_junk():
    import uuid as _uuid

    cam = str(_uuid.uuid4())
    j = SimpleNamespace(segments=[
        {"camera_id": cam}, {"camera_id": cam}, {"camera_id": "not-a-uuid"}, {},
    ])
    assert journey_camera_ids(j) == [_uuid.UUID(cam)]


def test_body_subjects_are_not_associable():
    """An appearance cluster does not survive a change of clothes, so it
    cannot carry a habit across days, which is the only thing an
    association is for."""
    assert "body" not in ASSOCIABLE_SUBJECT_KINDS
    assert ASSOCIABLE_SUBJECT_KINDS == {"person", "cluster"}


@pytest.mark.asyncio
async def test_process_journey_skips_body_subjects():
    j = SimpleNamespace(
        subject_kind="body", subject_key="bc-1",
        started_at=_at(1, 8), last_seen_at=_at(1, 9), ended_at=None,
        segments=[{"camera_id": "x"}],
    )
    assert await assoc_mod.process_journey(None, j, tz_name="UTC", min_days=3) == 0


@pytest.mark.asyncio
async def test_process_journey_skips_a_journey_with_no_window():
    j = SimpleNamespace(
        subject_kind="person", subject_key="Ahmed",
        started_at=None, last_seen_at=None, ended_at=None, segments=[],
    )
    assert await assoc_mod.process_journey(None, j, tz_name="UTC", min_days=3) == 0


# ---- declared edges are never touched by inference -----------------------


def test_learned_and_declared_are_separate_rows():
    """The unique constraint includes source, so an admin's authorization
    and an inferred habit over the same pair coexist rather than one
    overwriting the other."""
    from shared.models import EntityAssociation

    cols = {
        c.name
        for c in EntityAssociation.__table__.constraints
        if c.name == "uq_entity_association"
        for c in c.columns
    }
    assert "source" in cols
    assert {"subject_kind", "subject_key", "object_kind", "object_key",
            "relation", "source"} == cols


def test_span_of_a_month_of_mornings_establishes_the_edge():
    """The scenario this exists for, end to end over the pure path."""
    e = _edge()
    start = datetime(2026, 7, 1, 2, 15, tzinfo=timezone.utc)  # 08:15 Dhaka
    for day in range(30):
        fold(e, start + timedelta(days=day), "Asia/Dhaka", min_days=3)

    assert e.status == "established"
    assert e.distinct_days == 30
    assert e.hour_histogram == {"8": 30}
