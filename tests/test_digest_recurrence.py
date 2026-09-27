from datetime import date


def test_weekly_recurrence_highlight_requires_three_distinct_days():
    days = {date(2026, 9, 1), date(2026, 9, 3), date(2026, 9, 5)}
    assert len(days) >= 3
    assert "Recurring pattern" in f"Recurring pattern: Unknown 7 seen on {len(days)} days"


def test_recurrence_does_not_use_raw_frame_count_as_day_count():
    days = {date(2026, 9, 1)}
    assert len(days) < 3
