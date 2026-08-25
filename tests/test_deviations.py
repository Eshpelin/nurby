"""Deviation and authorization alerting over established edges (#149).

The point of these alerts is that they carry a reason. "Unknown vehicle
detected" tells a household nothing; "the Harrier normally leaves from
here around 08:00 and something else is parked there" tells them what to
do. These tests pin when each deviation fires and, more importantly, when
it stays quiet.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

from services.perception.deviations import (
    detect_expected_absent,
    detect_unauthorized,
    detect_unexpected_object,
    detect_wrong_time,
    is_alertable,
    usual_cameras,
    usual_hours,
)

CAM_A = "cam-driveway"
CAM_B = "cam-back"


def _edge(**kw):
    base = dict(
        id="e-1",
        subject_kind="person",
        subject_key="Ahmed",
        object_kind="vehicle",
        object_key="v-harrier",
        object_label="Harrier",
        relation="uses",
        source="learned",
        status="established",
        user_confirmed=False,
        evidence_count=30,
        distinct_days=30,
        last_day="2026-08-20",
        # Weekday mornings at 08:00, on the driveway.
        hour_histogram={"8": 28, "9": 2},
        dow_histogram={"0": 6, "1": 6, "2": 6, "3": 6, "4": 6},
        camera_histogram={CAM_A: 30},
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _at(hour, day=24, minute=0):
    # 2026-08-24 is a Monday.
    return datetime(2026, 8, day, hour, minute, tzinfo=timezone.utc)


# ---- unexpected object ---------------------------------------------------


def test_a_different_vehicle_in_the_usual_spot_at_the_usual_hour_fires():
    event = detect_unexpected_object(
        _edge(), present_object_key="v-stranger", camera_id=CAM_A,
        when=_at(8), tz_name="UTC",
    )
    assert event is not None
    assert event["deviation"] == "unexpected_object"
    assert event["expected_object_label"] == "Harrier"
    assert event["present_object_key"] == "v-stranger"
    # The reason is the whole point: the alert explains itself.
    assert "normally here" in event["reason"]


def test_the_usual_vehicle_is_not_a_deviation():
    assert detect_unexpected_object(
        _edge(), present_object_key="v-harrier", camera_id=CAM_A,
        when=_at(8), tz_name="UTC",
    ) is None


def test_a_different_vehicle_elsewhere_is_not_a_deviation():
    """The habit is about a place. A car on another camera violates no
    expectation."""
    assert detect_unexpected_object(
        _edge(), present_object_key="v-stranger", camera_id=CAM_B,
        when=_at(8), tz_name="UTC",
    ) is None


def test_a_different_vehicle_at_an_unremarkable_hour_is_not_a_deviation():
    """At 3am there is no expectation to violate, so this is a job for an
    ordinary unknown-vehicle rule, not for this one."""
    assert detect_unexpected_object(
        _edge(), present_object_key="v-stranger", camera_id=CAM_A,
        when=_at(3), tz_name="UTC",
    ) is None


def test_candidate_edges_never_alert():
    """A pattern that has not proved itself is noise, not an expectation."""
    assert detect_unexpected_object(
        _edge(status="candidate"), present_object_key="v-stranger",
        camera_id=CAM_A, when=_at(8), tz_name="UTC",
    ) is None


def test_declared_edges_never_produce_habit_deviations():
    """A declared edge is policy. It has no history to deviate from."""
    assert is_alertable(_edge(source="declared")) is False


def test_rejected_and_archived_edges_never_alert():
    assert is_alertable(_edge(status="rejected")) is False
    assert is_alertable(_edge(status="archived")) is False


# ---- wrong time ----------------------------------------------------------


def test_the_usual_pairing_at_an_odd_hour_fires():
    event = detect_wrong_time(_edge(), camera_id=CAM_A, when=_at(2), tz_name="UTC")
    assert event is not None
    assert event["deviation"] == "wrong_time"
    assert event["hour"] == 2


def test_an_adjacent_hour_is_not_wrong():
    """A habit is not a timetable. Leaving at 07:00 instead of 08:00 is
    not news, and alerting on it would train people to ignore alerts."""
    assert detect_wrong_time(_edge(), camera_id=CAM_A, when=_at(7), tz_name="UTC") is None


def test_an_edge_with_no_hour_history_cannot_be_wrong():
    assert detect_wrong_time(
        _edge(hour_histogram={}), camera_id=CAM_A, when=_at(3), tz_name="UTC"
    ) is None


# ---- expected absent -----------------------------------------------------


def test_a_habit_that_has_not_happened_by_now_fires():
    """Monday, well past the usual hour, nothing today."""
    event = detect_expected_absent(
        _edge(last_day="2026-08-21"), now=_at(11), tz_name="UTC"
    )
    assert event is not None
    assert event["deviation"] == "expected_absent"


def test_nothing_fires_inside_the_grace_window():
    assert detect_expected_absent(
        _edge(last_day="2026-08-21"), now=_at(9), tz_name="UTC"
    ) is None


def test_nothing_fires_once_it_has_happened_today():
    assert detect_expected_absent(
        _edge(last_day="2026-08-24"), now=_at(11), tz_name="UTC"
    ) is None


def test_a_weekday_habit_says_nothing_about_a_weekend():
    """2026-08-23 is a Sunday, and this edge has never been seen on one."""
    assert detect_expected_absent(
        _edge(last_day="2026-08-21"), now=_at(11, day=23), tz_name="UTC"
    ) is None


# ---- unauthorized (policy, not habit) ------------------------------------


def _declared(subject_key, object_key="v-forklift3"):
    return SimpleNamespace(
        subject_kind="person", subject_key=subject_key,
        object_kind="vehicle", object_key=object_key,
        relation="authorized_for", source="declared", status="established",
        object_label="Forklift 3",
    )


def test_use_without_a_declaration_fires():
    used = _edge(subject_key="Worker-7", object_key="v-forklift3",
                 object_label="Forklift 3", status="candidate")
    event = detect_unauthorized(used, [_declared("Worker-1"), _declared("Worker-2")])

    assert event is not None
    assert event["deviation"] == "unauthorized"
    assert event["subject_key"] == "Worker-7"
    assert event["authorized_subjects"] == ["Worker-1", "Worker-2"]


def test_a_declared_operator_does_not_fire():
    used = _edge(subject_key="Worker-1", object_key="v-forklift3", status="candidate")
    assert detect_unauthorized(used, [_declared("Worker-1")]) is None


def test_an_object_nobody_declared_is_nobody_s_violation():
    """The absence of a policy is not a policy. Without a declared
    authorization the object is simply not access-controlled."""
    used = _edge(subject_key="Worker-7", object_key="v-forklift3", status="candidate")
    assert detect_unauthorized(used, []) is None


def test_declarations_for_another_object_do_not_restrict_this_one():
    used = _edge(subject_key="Worker-7", object_key="v-forklift9", status="candidate")
    assert detect_unauthorized(used, [_declared("Worker-1", "v-forklift3")]) is None


def test_authorization_does_not_depend_on_the_habit_being_established():
    """Policy applies on the first use, not after it becomes a habit.
    Waiting for three days would mean three days of unpermitted use."""
    used = _edge(subject_key="Worker-7", object_key="v-forklift3",
                 status="candidate", distinct_days=1, evidence_count=1)
    assert detect_unauthorized(used, [_declared("Worker-1")]) is not None


def test_a_declared_edge_is_never_itself_an_unauthorized_use():
    declared_use = _edge(source="declared", relation="uses")
    assert detect_unauthorized(declared_use, [_declared("Worker-1")]) is None


# ---- reading histograms --------------------------------------------------


def test_usual_hours_ignores_thin_tails():
    edge = _edge(hour_histogram={"8": 95, "3": 5})
    assert usual_hours(edge) == {8}


def test_usual_hours_keeps_a_spread_out_habit():
    """Someone who leaves anywhere between 07:00 and 09:00 has a pattern,
    not an absence of one."""
    edge = _edge(hour_histogram={"7": 10, "8": 12, "9": 8})
    assert usual_hours(edge) == {7, 8, 9}


def test_empty_histograms_are_empty_not_wrong():
    assert usual_hours(_edge(hour_histogram=None)) == set()
    assert usual_cameras(_edge(camera_histogram={})) == set()


def test_local_time_decides_the_hour():
    """02:00 UTC is 08:00 in Dhaka, which is when this habit happens."""
    event = detect_unexpected_object(
        _edge(), present_object_key="v-stranger", camera_id=CAM_A,
        when=datetime(2026, 8, 24, 2, 0, tzinfo=timezone.utc),
        tz_name="Asia/Dhaka",
    )
    assert event is not None and event["hour"] == 8
