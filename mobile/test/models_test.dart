import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/models/models.dart';

void main() {
  group('Camera', () {
    test('parses full payload and keeps raw', () {
      final camera = Camera.fromJson({
        'id': 'cam-1',
        'name': 'Front Door',
        'stream_type': 'rtsp',
        'stream_url': 'rtsp://10.0.0.5:8554/front_door',
        'enabled': true,
        'is_online': true,
        'recording_enabled': true,
        'detect_objects': true,
        'detect_faces': false,
        'display_order': 2,
        'retention_days': 14,
      });
      expect(camera.name, 'Front Door');
      expect(camera.online, isTrue);
      expect(camera.displayOrder, 2);
      expect(camera.raw['retention_days'], 14);
    });

    test('tolerates missing optional fields', () {
      final camera = Camera.fromJson({'id': 'x'});
      expect(camera.name, 'Camera');
      expect(camera.online, isFalse);
      expect(camera.streamUrl, isNull);
    });
  });

  group('Observation', () {
    test('parses nested detection JSON', () {
      final obs = Observation.fromJson({
        'id': 'o1',
        'camera_id': 'cam-1',
        'started_at': '2026-07-04T10:00:00Z',
        'vlm_description': 'A person walks by',
        'object_detections': {
          'detections': [
            {
              'label': 'person',
              'confidence': 0.93,
              'x1': 10.0,
              'y1': 20.0,
              'x2': 110.0,
              'y2': 220.0,
            },
            {
              'label': 'dog',
              'confidence': 0.81,
              'x1': 0.0,
              'y1': 0.0,
              'x2': 50.0,
              'y2': 50.0,
            },
          ]
        },
        'person_detections': {
          'persons': [
            {
              'person_id': 'p1',
              'person_name': 'Sana',
              'confidence': 0.88,
              'x1': 10.0,
              'y1': 20.0,
              'x2': 110.0,
              'y2': 220.0,
            }
          ]
        },
      });
      expect(obs.objectDetections, hasLength(2));
      expect(obs.labels, containsAll(['person', 'dog']));
      expect(obs.personDetections.single.personName, 'Sana');
      expect(obs.startedAt.isUtc, isFalse); // converted to local
    });

    test('handles null detection blocks', () {
      final obs = Observation.fromJson({
        'id': 'o2',
        'camera_id': 'c',
        'started_at': '2026-07-04T10:00:00Z',
      });
      expect(obs.objectDetections, isEmpty);
      expect(obs.personDetections, isEmpty);
    });
  });

  group('Event', () {
    test('acked derived from acked_at', () {
      final acked = Event.fromJson({
        'id': 'e1',
        'rule_id': 'r1',
        'rule_name': 'Stranger at night',
        'fired_at': '2026-07-04T02:13:00Z',
        'acked_at': '2026-07-04T08:00:00Z',
      });
      final open = Event.fromJson({
        'id': 'e2',
        'rule_id': 'r1',
        'rule_name': 'Stranger at night',
        'fired_at': '2026-07-04T02:13:00Z',
      });
      expect(acked.acked, isTrue);
      expect(open.acked, isFalse);
    });
  });

  group('Rule', () {
    test('parses trigger/conditions/actions and snooze state', () {
      final rule = Rule.fromJson({
        'id': 'r1',
        'name': 'Person at door',
        'enabled': true,
        'trigger_pattern': {'label': 'person', 'confidence_min': 0.8},
        'conditions': {'after': '22:00', 'before': '06:00'},
        'actions': [
          {'type': 'telegram', 'channel_id': 'ch1', 'message': 'hi'}
        ],
        'cooldown_seconds': 300,
        'snoozed_until':
            DateTime.now().add(const Duration(hours: 1)).toIso8601String(),
      });
      expect(rule.triggerPattern['label'], 'person');
      expect(rule.actions.single['type'], 'telegram');
      expect(rule.snoozed, isTrue);
    });
  });

  group('TimelineItem', () {
    test('observation kind embeds Observation', () {
      final item = TimelineItem.fromJson({
        'kind': 'observation',
        'id': 'o1',
        'camera_id': 'c1',
        'started_at': '2026-07-04T09:12:00Z',
        'vlm_description': 'desc',
      });
      expect(item.observation, isNotNull);
      expect(item.text, 'desc');
    });

    test('transcript kind uses text', () {
      final item = TimelineItem.fromJson({
        'kind': 'transcript',
        'id': 't1',
        'camera_id': 'c1',
        'started_at': '2026-07-04T09:12:00Z',
        'text': 'hello there',
      });
      expect(item.observation, isNull);
      expect(item.text, 'hello there');
    });
  });
}
