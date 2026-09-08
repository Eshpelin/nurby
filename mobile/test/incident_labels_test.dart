import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/features/incidents/incidents_screen.dart';
import 'package:nurby_mobile/features/journeys/journeys_screen.dart';
import 'package:nurby_mobile/models/models.dart';

Incident _incident({required String kind, required String key}) =>
    Incident.fromJson({
      'id': 'i1',
      'camera_id': 'c1',
      'signature_kind': kind,
      'signature_key': key,
      'started_at': '2026-09-08T10:00:00Z',
      'last_seen_at': '2026-09-08T10:04:30Z',
    });

Journey _journey({required String kind, required String key, List? segments}) =>
    Journey.fromJson({
      'id': 'j1',
      'subject_kind': kind,
      'subject_key': key,
      'started_at': '2026-09-08T10:00:00Z',
      'last_seen_at': '2026-09-08T10:10:00Z',
      if (segments != null) 'segments': segments,
    });

void main() {
  group('incidentTitle', () {
    test('a person is shown by name, several names read as a list', () {
      expect(incidentTitle(_incident(kind: 'person', key: 'Sam')), 'Sam');
      expect(incidentTitle(_incident(kind: 'person', key: 'Sam,Alex')),
          'Sam, Alex');
    });

    test('a cluster never shows the household its raw id', () {
      final title = incidentTitle(
          _incident(kind: 'cluster', key: '9f3ab120-4c5d-4e6f-8a9b-000000000001'));
      expect(title, startsWith('Recurring stranger '));
      expect(title, isNot(contains('4c5d')));
    });

    test('a short cluster key does not overflow the shortening', () {
      expect(incidentTitle(_incident(kind: 'cluster', key: 'ab')),
          'Recurring stranger ab');
    });

    test('body matching is stated as appearance, not as identity', () {
      expect(incidentTitle(_incident(kind: 'body', key: 'x')),
          'Unrecognized person (matched by appearance)');
    });

    test('object labels are capitalized and extras are counted', () {
      expect(incidentTitle(_incident(kind: 'object', key: 'dog')), 'Dog');
      expect(incidentTitle(_incident(kind: 'object', key: 'dog,car,bike')),
          'Dog and 2 more');
    });

    test('an unrecognised kind falls back to motion rather than a raw key', () {
      expect(incidentTitle(_incident(kind: 'something-new', key: 'raw-key')),
          'Motion');
    });
  });

  group('formatDuration', () {
    test('reads in the largest unit that still says something', () {
      expect(formatDuration(const Duration(seconds: 42)), '42s');
      expect(formatDuration(const Duration(minutes: 7, seconds: 30)), '7m');
      expect(formatDuration(const Duration(hours: 2)), '2h');
      expect(formatDuration(const Duration(hours: 2, minutes: 5)), '2h 5m');
    });
  });

  test('Incident.duration spans first to last sighting', () {
    expect(_incident(kind: 'motion', key: '').duration,
        const Duration(minutes: 4, seconds: 30));
  });

  group('journeySubject', () {
    test('mirrors the incident rules for the same kinds', () {
      expect(journeySubject(_journey(kind: 'person', key: 'Sam,Alex')),
          'Sam, Alex');
      expect(journeySubject(_journey(kind: 'body', key: 'x')),
          'Unrecognized person (matched by appearance)');
      expect(journeySubject(_journey(kind: 'cluster', key: 'abcdefghijk')),
          'Recurring stranger abcdefgh');
    });

    test('an empty key reads as unknown rather than as a blank line', () {
      expect(journeySubject(_journey(kind: 'other', key: '')), 'Unknown');
    });
  });

  group('Journey.cameraPath', () {
    test('keeps order and collapses a subject lingering on one camera', () {
      final j = _journey(kind: 'person', key: 'Sam', segments: [
        {'camera_name': 'Front door'},
        {'camera_name': 'Front door'},
        {'camera_name': 'Hallway'},
        {'camera_name': 'Front door'},
      ]);
      expect(j.cameraPath, ['Front door', 'Hallway', 'Front door']);
    });

    test('drops segments with no usable camera name', () {
      final j = _journey(kind: 'person', key: 'Sam', segments: [
        {'camera_name': null},
        {'camera_name': ''},
        {'camera_name': 'Garage'},
      ]);
      expect(j.cameraPath, ['Garage']);
    });
  });

  group('DigestEntry', () {
    test('a null camera means the digest covers the whole household', () {
      final d = DigestEntry.fromJson({
        'id': 'd1',
        'period': 'daily',
        'summary': 'Quiet day.',
        'generated_at': '2026-09-08T22:00:00Z',
        'camera_id': null,
        'highlights': ['One delivery'],
        'total_observations': 12,
      });
      expect(d.cameraId, isNull);
      expect(d.highlights, ['One delivery']);
      expect(d.totalObservations, 12);
    });
  });

  group('Conversation', () {
    test('an unfinalized conversation still parses with no end time', () {
      final c = Conversation.fromJson({
        'id': 'v1',
        'camera_id': 'c1',
        'started_at': '2026-09-08T10:00:00Z',
        'ended_at_provisional': '2026-09-08T10:01:00Z',
        'transcript_count': 3,
        'speakers_seen': ['Sam'],
      });
      expect(c.endedAt, isNull);
      expect(c.finalized, isFalse);
      expect(c.speakersSeen, ['Sam']);
    });
  });

  group('ConversationTranscript.edited', () {
    test('a never-edited line is not marked corrected', () {
      final t = ConversationTranscript.fromJson({
        'id': 't1',
        'started_at': '2026-09-08T10:00:00Z',
        'text': 'hello',
        'original_text': null,
      });
      expect(t.edited, isFalse);
    });

    test('a corrected line is marked, and keeps what was heard', () {
      // Showing the fixed text as if that is what was heard would be a
      // quiet lie. The original has to survive the round trip.
      final t = ConversationTranscript.fromJson({
        'id': 't1',
        'started_at': '2026-09-08T10:00:00Z',
        'text': 'Simon',
        'original_text': 'salmon',
      });
      expect(t.edited, isTrue);
      expect(t.originalText, 'salmon');
    });

    test('an edit that restored the original is not marked', () {
      final t = ConversationTranscript.fromJson({
        'id': 't1',
        'started_at': '2026-09-08T10:00:00Z',
        'text': 'hello',
        'original_text': 'hello',
      });
      expect(t.edited, isFalse);
    });
  });
}
