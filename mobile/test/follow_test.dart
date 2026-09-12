import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/features/follow/follow_screen.dart';
import 'package:nurby_mobile/models/models.dart';

Map<String, dynamic> _bundle({
  Map<String, dynamic>? subject,
  Map<String, dynamic>? hourBuckets,
  List<Map<String, dynamic>> feed = const [],
  List<Map<String, dynamic>> cameras = const [],
}) =>
    {
      'subject': subject ??
          {
            'kind': 'person',
            'id': 'p1',
            'display_name': 'Sam',
            'relationship': 'housemate',
          },
      'stats': {
        'total_sightings': 3,
        'first_seen_at': '2026-09-08T07:15:00Z',
        'last_seen_at': '2026-09-08T19:40:00Z',
        'cameras_seen': cameras,
        'hour_buckets': hourBuckets ?? {'07': 1, '19': 2},
        'incidents_count': 1,
        'conversations_count': 0,
        'recordings_count': 2,
      },
      'feed': feed,
    };

void main() {
  group('FollowSubject.title', () {
    test('a person is shown by name', () {
      final b = FollowBundle.fromJson(_bundle());
      expect(b.subject.title, 'Sam');
      expect(b.subject.subtitle, 'housemate');
    });

    test('a person with no name says so rather than showing an id', () {
      final b = FollowBundle.fromJson(_bundle(subject: {
        'kind': 'person',
        'id': '9f3ab120-4c5d-4e6f-8a9b-000000000001',
        'display_name': '',
      }));
      expect(b.subject.title, 'Unnamed');
      expect(b.subject.title, isNot(contains('9f3ab120')));
    });

    test('a cluster uses its auto label, never its uuid', () {
      final b = FollowBundle.fromJson(_bundle(subject: {
        'kind': 'cluster',
        'id': '9f3ab120-4c5d-4e6f-8a9b-000000000001',
        'auto_label': 'Unknown person 4',
        'appearance_description': 'dark jacket',
      }));
      expect(b.subject.title, 'Unknown person 4');
      expect(b.subject.subtitle, 'dark jacket');
      expect(b.subject.title, isNot(contains('4c5d')));
    });

    test('a cluster with only a number still reads as a person', () {
      final b = FollowBundle.fromJson(_bundle(subject: {
        'kind': 'cluster',
        'id': 'c1',
        'auto_label_number': 7,
      }));
      expect(b.subject.title, 'Unknown person 7');
    });

    test('a cluster with nothing at all does not render a blank header', () {
      final b = FollowBundle.fromJson(
          _bundle(subject: {'kind': 'cluster', 'id': 'c1'}));
      expect(b.subject.title, 'Unknown person');
    });
  });

  group('FollowStats.hoursOfDay', () {
    test('zero-fills the hours the API omits', () {
      // The API only sends hours that have sightings. Building a heatmap
      // straight off that map would drop the quiet hours and compress a
      // 3am visit next to a 9am one, which reads as routine.
      final b = FollowBundle.fromJson(_bundle());
      final hours = b.stats.hoursOfDay;
      expect(hours, hasLength(24));
      expect(hours[7], 1);
      expect(hours[19], 2);
      expect(hours[3], 0);
      expect(hours.fold<int>(0, (a, x) => a + x), 3);
    });

    test('an empty bucket map is still 24 zeroes, not an empty list', () {
      final b = FollowBundle.fromJson(_bundle(hourBuckets: const {}));
      expect(b.stats.hoursOfDay, hasLength(24));
      expect(b.stats.hoursOfDay.every((h) => h == 0), isTrue);
    });

    test('hour keys are read as two-digit strings', () {
      // "07" not 7. Reading these as ints would silently blank the
      // morning.
      final b = FollowBundle.fromJson(_bundle(hourBuckets: const {'00': 5}));
      expect(b.stats.hoursOfDay[0], 5);
    });
  });

  group('feed parsing', () {
    test('keeps kind-specific fields available in raw', () {
      final b = FollowBundle.fromJson(_bundle(feed: [
        {
          'kind': 'recording',
          'id': 'r1',
          'camera_id': 'c1',
          'camera_name': 'Front door',
          'ts': '2026-09-08T19:40:00Z',
          'duration_seconds': 95,
        },
      ]));
      final item = b.feed.single;
      expect(item.kind, 'recording');
      expect(item.cameraName, 'Front door');
      expect(item.raw['duration_seconds'], 95);
    });

    test('an unknown feed kind still parses with its shared fields', () {
      // The API can grow a kind before the app knows about it. Dropping
      // the row would silently hide activity from an investigation.
      final b = FollowBundle.fromJson(_bundle(feed: [
        {
          'kind': 'something_new',
          'id': 'x1',
          'ts': '2026-09-08T19:40:00Z',
          'camera_name': 'Hallway',
        },
      ]));
      expect(b.feed, hasLength(1));
      expect(b.feed.single.kind, 'something_new');
      expect(b.feed.single.cameraName, 'Hallway');
    });
  });

  group('FollowQuery', () {
    test('equal queries share a provider cache entry', () {
      const a = FollowQuery(kind: 'person', id: 'p1', cameraIds: ['c1', 'c2']);
      const b = FollowQuery(kind: 'person', id: 'p1', cameraIds: ['c1', 'c2']);
      expect(a, b);
      expect(a.hashCode, b.hashCode);
    });

    test('a different camera filter is a different query', () {
      // Riverpod families key on equality. If two filters compared equal
      // the screen would keep showing the previous camera's results.
      const a = FollowQuery(kind: 'person', id: 'p1', cameraIds: ['c1']);
      const b = FollowQuery(kind: 'person', id: 'p1', cameraIds: ['c2']);
      expect(a == b, isFalse);
    });

    test('the same id under a different kind is a different query', () {
      const a = FollowQuery(kind: 'person', id: 'x');
      const b = FollowQuery(kind: 'cluster', id: 'x');
      expect(a == b, isFalse);
    });

    test('withCameras keeps the subject and swaps the filter', () {
      const a = FollowQuery(kind: 'cluster', id: 'c9', cameraIds: ['c1']);
      final b = a.withCameras(const ['c2', 'c3']);
      expect(b.kind, 'cluster');
      expect(b.id, 'c9');
      expect(b.cameraIds, ['c2', 'c3']);
    });
  });
}
