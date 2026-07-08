import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/core/push.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Records show() calls instead of touching platform channels.
class _RecordingNotificationService extends NotificationService {
  final List<(String title, String body)> shown = [];

  @override
  Future<void> show(String title, String body, {String? payload}) async {
    shown.add((title, body));
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('countNewAlerts', () {
    test('first run (no baseline) reports nothing', () {
      expect(countNewAlerts(unread: 5, unreviewed: 3), 0);
    });

    test('growth in unread only', () {
      expect(
        countNewAlerts(
            unread: 4, unreviewed: 2, lastUnread: 1, lastUnreviewed: 2),
        3,
      );
    });

    test('growth in both counters is summed', () {
      expect(
        countNewAlerts(
            unread: 4, unreviewed: 5, lastUnread: 2, lastUnreviewed: 1),
        6,
      );
    });

    test('unchanged counts report nothing', () {
      expect(
        countNewAlerts(
            unread: 2, unreviewed: 7, lastUnread: 2, lastUnreviewed: 7),
        0,
      );
    });

    test('shrinking counts (read or acked elsewhere) report nothing', () {
      expect(
        countNewAlerts(
            unread: 0, unreviewed: 1, lastUnread: 5, lastUnreviewed: 4),
        0,
      );
    });

    test('mixed shrink and growth only counts the growth', () {
      expect(
        countNewAlerts(
            unread: 0, unreviewed: 6, lastUnread: 5, lastUnreviewed: 4),
        2,
      );
    });

    test('partial baseline: only the known counter can grow', () {
      expect(
        countNewAlerts(unread: 9, unreviewed: 9, lastUnreviewed: 4),
        5,
      );
    });
  });

  group('applyAlertCounts', () {
    Future<SharedPreferences> prefsWith(Map<String, Object> values) async {
      SharedPreferences.setMockInitialValues(values);
      return SharedPreferences.getInstance();
    }

    test('first run stores the baseline and stays silent', () async {
      final prefs = await prefsWith({});
      final notifications = _RecordingNotificationService();

      final result = await applyAlertCounts(
        prefs: prefs,
        notifications: notifications,
        unread: 3,
        unreviewed: 7,
      );

      expect(result.newAlerts, 0);
      expect(notifications.shown, isEmpty);
      expect(prefs.getInt(kLastUnreadKey), 3);
      expect(prefs.getInt(kLastUnreviewedKey), 7);
    });

    test('fires one notification with the grown count', () async {
      final prefs =
          await prefsWith({kLastUnreadKey: 1, kLastUnreviewedKey: 2});
      final notifications = _RecordingNotificationService();

      final result = await applyAlertCounts(
        prefs: prefs,
        notifications: notifications,
        unread: 3,
        unreviewed: 4,
      );

      expect(result.newAlerts, 4);
      expect(notifications.shown, [('Nurby', '4 new alerts')]);
      expect(prefs.getInt(kLastUnreadKey), 3);
      expect(prefs.getInt(kLastUnreviewedKey), 4);
    });

    test('uses singular wording for a single new alert', () async {
      final prefs =
          await prefsWith({kLastUnreadKey: 0, kLastUnreviewedKey: 0});
      final notifications = _RecordingNotificationService();

      final result = await applyAlertCounts(
        prefs: prefs,
        notifications: notifications,
        unread: 1,
        unreviewed: 0,
      );

      expect(result.newAlerts, 1);
      expect(notifications.shown, [('Nurby', '1 new alert')]);
    });

    test('stays silent when counts shrink but still updates baseline',
        () async {
      final prefs =
          await prefsWith({kLastUnreadKey: 5, kLastUnreviewedKey: 5});
      final notifications = _RecordingNotificationService();

      final result = await applyAlertCounts(
        prefs: prefs,
        notifications: notifications,
        unread: 0,
        unreviewed: 2,
      );

      expect(result.newAlerts, 0);
      expect(notifications.shown, isEmpty);
      expect(prefs.getInt(kLastUnreadKey), 0);
      expect(prefs.getInt(kLastUnreviewedKey), 2);
    });

    test('repeat check with unchanged counts stays silent', () async {
      final prefs =
          await prefsWith({kLastUnreadKey: 2, kLastUnreviewedKey: 3});
      final notifications = _RecordingNotificationService();

      final result = await applyAlertCounts(
        prefs: prefs,
        notifications: notifications,
        unread: 2,
        unreviewed: 3,
      );

      expect(result.newAlerts, 0);
      expect(notifications.shown, isEmpty);
    });
  });
}
