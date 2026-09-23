"""Expected-activity evaluation foundation (#215)."""

from datetime import datetime, time, timezone

from services.perception.expected_activity import ExpectedWindow, evaluate_window


WINDOW = ExpectedWindow(
    subject_key="Mom",
    weekdays=frozenset({0}),  # Monday
    start=time(9),
    end=time(10),
    camera_ids=frozenset({"kitchen"}),
)


def test_satisfied_window_returns_matching_evidence():
    out = evaluate_window(
        WINDOW,
        local_now=datetime(2026, 9, 21, 10, 1, tzinfo=timezone.utc),
        sightings=[{"subject_key": "Mom", "camera_id": "kitchen", "at": "09:42"}],
    )
    assert out["status"] == "satisfied"
    assert out["sighting"]["at"] == "09:42"


def test_missing_sighting_with_healthy_coverage_is_a_violation():
    out = evaluate_window(
        WINDOW,
        local_now=datetime(2026, 9, 21, 10, 1, tzinfo=timezone.utc),
        sightings=[],
        last_seen={"camera_id": "kitchen", "at": "yesterday 09:42"},
        coverage=[{"camera_id": "kitchen", "camera_name": "Kitchen", "evidence_state": "quiet"}],
    )
    assert out["status"] == "violated"
    assert out["last_seen"]["at"] == "yesterday 09:42"


def test_missing_sighting_during_degraded_coverage_is_unknown_not_violation():
    out = evaluate_window(
        WINDOW,
        local_now=datetime(2026, 9, 21, 10, 1, tzinfo=timezone.utc),
        sightings=[],
        coverage=[{
            "camera_id": "kitchen",
            "camera_name": "Kitchen",
            "evidence_state": "degraded",
            "gaps": ["frozen"],
        }],
    )
    assert out["status"] == "unknown"
    assert out["coverage_gaps"][0]["evidence_state"] == "degraded"


def test_wrong_weekday_is_not_a_violation():
    out = evaluate_window(
        WINDOW,
        local_now=datetime(2026, 9, 22, 10, 1, tzinfo=timezone.utc),
        sightings=[],
    )
    assert out["status"] == "not_applicable"
