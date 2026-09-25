"""First-run wizard funnel counters (#293). The endpoint handler is a thin
wrapper over app settings; the contract under test is the pure event
validation and counter arithmetic, plus that metrics surface the funnel.
"""

from shared.onboarding_metrics import (
    FUNNEL_EVENTS,
    OnboardingMetrics,
    bump_funnel,
    compute_metrics,
    normalize_funnel_event,
)


def test_only_known_events_pass_validation():
    for event in FUNNEL_EVENTS:
        assert normalize_funnel_event(event) == event
    assert normalize_funnel_event("wizard_shown ") is None
    assert normalize_funnel_event("WIZARD_SHOWN") is None
    assert normalize_funnel_event("drop table") is None
    assert normalize_funnel_event(None) is None
    assert normalize_funnel_event(42) is None


def test_bump_is_pure_and_accumulates():
    counts = {}
    once = bump_funnel(counts, "wizard_shown")
    twice = bump_funnel(once, "wizard_shown")
    magic = bump_funnel(twice, "magic_clicked")
    assert counts == {}  # input never mutated
    assert once == {"wizard_shown": 1}
    assert twice == {"wizard_shown": 2}
    assert magic == {"wizard_shown": 2, "magic_clicked": 1}


def test_metrics_surface_the_funnel():
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    metrics = compute_metrics([], [], now=now, funnel={"wizard_shown": 5})
    assert isinstance(metrics, OnboardingMetrics)
    assert metrics.funnel == {"wizard_shown": 5}
    assert compute_metrics([], [], now=now).funnel == {}
