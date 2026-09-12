import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/features/reports/reports_screen.dart';
import 'package:nurby_mobile/models/models.dart';

ScheduledReport _report({
  List<String>? days,
  int hour = 19,
  int minute = 0,
  Map<String, dynamic> delivery = const {},
}) =>
    ScheduledReport.fromJson({
      'id': 'r1',
      'name': 'Evening check',
      'prompt': 'What did Sam do today?',
      'hour': hour,
      'minute': minute,
      'enabled': true,
      'days': days,
      'delivery': delivery,
    });

void main() {
  group('scheduleLabel', () {
    test('null days is every day', () {
      expect(scheduleLabel(_report(days: null)), 'Every day at 19:00');
    });

    test('an empty list is also every day', () {
      // The server normalises [] to null. Both must read the same, or a
      // report saved from mobile would read differently from one saved
      // on web.
      expect(scheduleLabel(_report(days: const [])), 'Every day at 19:00');
    });

    test('recognises weekdays', () {
      expect(
        scheduleLabel(_report(days: const ['mon', 'tue', 'wed', 'thu', 'fri'])),
        'Weekdays at 19:00',
      );
    });

    test('recognises weekends regardless of order', () {
      expect(scheduleLabel(_report(days: const ['sun', 'sat'])),
          'Weekends at 19:00');
    });

    test('lists other selections in week order, not selection order', () {
      expect(
        scheduleLabel(_report(days: const ['fri', 'mon'], hour: 7, minute: 30)),
        'Mon, Fri at 07:30',
      );
    });

    test('pads the time', () {
      expect(_report(hour: 7, minute: 5).timeLabel, '07:05');
    });
  });

  group('deliveryLabels', () {
    test('notify defaults to on when absent', () {
      // The scheduler treats a missing key as true, so a report created
      // on web with no delivery block still goes in-app.
      expect(deliveryLabels(const {}), ['in app']);
    });

    test('notify false removes in-app', () {
      expect(deliveryLabels(const {'notify': false}), isEmpty);
    });

    test('lists every configured channel', () {
      expect(
        deliveryLabels(const {
          'notify': true,
          'email': 'a@b.c',
          'telegram_channel_id': '123',
          'webhook': 'https://x',
        }),
        ['in app', 'email', 'Telegram', 'webhook'],
      );
    });

    test('a blank email does not count as a channel', () {
      expect(deliveryLabels(const {'email': '   '}), ['in app']);
    });

    test('a numeric telegram id is still a channel', () {
      expect(deliveryLabels(const {'telegram_channel_id': 123}),
          ['in app', 'Telegram']);
    });
  });

  group('ScheduledReport', () {
    test('parses a failed last run', () {
      final r = ScheduledReport.fromJson({
        'id': 'r1',
        'name': 'x',
        'prompt': 'y',
        'hour': 1,
        'minute': 2,
        'enabled': false,
        'last_run_at': '2026-09-09T19:00:00Z',
        'last_status': 'failed',
        'last_output': null,
      });
      expect(r.enabled, isFalse);
      expect(r.lastStatus, 'failed');
      expect(r.lastRunAt, isNotNull);
      expect(r.lastOutput, isNull);
    });
  });
}
