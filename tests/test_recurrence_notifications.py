from uuid import uuid4

from services.perception.recurrence_notifications import (
    RECURRENCE_THRESHOLD_DAYS,
    recurrence_notification_marker,
    should_notify_recurrence,
)


def test_recurrence_notification_waits_for_distinct_day_threshold():
    assert not should_notify_recurrence(RECURRENCE_THRESHOLD_DAYS - 1, False)
    assert should_notify_recurrence(RECURRENCE_THRESHOLD_DAYS, False)


def test_recurrence_notification_is_one_shot():
    assert not should_notify_recurrence(RECURRENCE_THRESHOLD_DAYS + 4, True)


def test_recurrence_marker_is_stable_and_scoped_to_cluster():
    cluster_id = uuid4()
    marker = recurrence_notification_marker("face", cluster_id)
    assert marker == f"recurring_unknown:face:{cluster_id}"
    assert marker != recurrence_notification_marker("body", cluster_id)
