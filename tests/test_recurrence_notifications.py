from uuid import uuid4

from services.perception.recurrence_notifications import (
    RECURRENCE_THRESHOLD_DAYS,
    reconcile_recurrence_notifications,
    recurrence_notification_marker,
    should_notify_recurrence,
)


def test_recurrence_notification_waits_for_distinct_day_threshold():
    assert not should_notify_recurrence(RECURRENCE_THRESHOLD_DAYS - 1, False)
    assert should_notify_recurrence(RECURRENCE_THRESHOLD_DAYS, False)


def test_recurrence_threshold_can_be_tuned_without_changing_default():
    assert not should_notify_recurrence(2, False, threshold_days=3)
    assert should_notify_recurrence(2, False, threshold_days=2)
    assert should_notify_recurrence(1, False, threshold_days=0)


def test_recurrence_notification_is_one_shot():
    assert not should_notify_recurrence(RECURRENCE_THRESHOLD_DAYS + 4, True)


def test_recurrence_marker_is_stable_and_scoped_to_cluster():
    cluster_id = uuid4()
    marker = recurrence_notification_marker("face", cluster_id)
    assert marker == f"recurring_unknown:face:{cluster_id}"
    assert marker != recurrence_notification_marker("body", cluster_id)


def test_recurrence_marker_is_metadata_not_user_facing_copy():
    cluster_id = uuid4()
    marker = recurrence_notification_marker("face", cluster_id)
    message = "The same unknown person has appeared on 3 separate days."
    assert marker not in message


def test_merge_recurrence_alerts_keeps_one_active_canonical_alert():
    class Notification:
        def __init__(self, created_at, identifier):
            self.created_at = created_at
            self.id = identifier
            self.dedupe_key = "old-marker"
            self.read = False

    first = Notification(1, "first")
    second = Notification(2, "second")
    canonical = reconcile_recurrence_notifications(
        [second, first], "recurring_unknown:face:survivor"
    )

    assert canonical is first
    assert first.dedupe_key == "recurring_unknown:face:survivor"
    assert not first.read
    assert second.dedupe_key is None
    assert second.read


def test_merge_recurrence_alerts_is_safe_when_no_alert_exists():
    assert reconcile_recurrence_notifications([], "survivor") is None
