/// Core domain models mapped from the Nurby API.
/// Pragmatic manual JSON mapping; only fields the UI consumes.
library;

DateTime? _date(dynamic v) => v == null ? null : DateTime.tryParse(v as String)?.toLocal();

class User {
  User({
    required this.id,
    required this.email,
    required this.displayName,
    required this.role,
  });

  factory User.fromJson(Map<String, dynamic> j) => User(
        id: j['id'] as String,
        email: j['email'] as String? ?? '',
        displayName: j['display_name'] as String? ?? '',
        role: j['role'] as String? ?? 'viewer',
      );

  final String id;
  final String email;
  final String displayName;
  final String role;

  bool get isAdmin => role == 'admin';
}

class Camera {
  Camera({
    required this.id,
    required this.name,
    required this.streamType,
    required this.enabled,
    required this.online,
    required this.recordingEnabled,
    required this.detectObjects,
    required this.detectFaces,
    this.streamUrl,
    this.vlmPrompt,
    this.displayOrder,
    this.raw = const {},
  });

  factory Camera.fromJson(Map<String, dynamic> j) => Camera(
        id: j['id'] as String,
        name: j['name'] as String? ?? 'Camera',
        streamType: j['stream_type'] as String? ?? 'rtsp',
        enabled: j['enabled'] as bool? ?? true,
        online: j['is_online'] as bool? ?? j['online'] as bool? ?? false,
        recordingEnabled: j['recording_enabled'] as bool? ?? false,
        detectObjects: j['detect_objects'] as bool? ?? false,
        detectFaces: j['detect_faces'] as bool? ?? false,
        streamUrl: j['stream_url'] as String?,
        vlmPrompt: j['vlm_prompt'] as String?,
        displayOrder: j['display_order'] as int?,
        raw: j,
      );

  final String id;
  final String name;
  final String streamType;
  final bool enabled;
  final bool online;
  final bool recordingEnabled;
  final bool detectObjects;
  final bool detectFaces;
  final String? streamUrl;
  final String? vlmPrompt;
  final int? displayOrder;

  /// Full server payload, kept for the settings editor so PATCHes can
  /// round-trip fields the app does not model explicitly.
  final Map<String, dynamic> raw;
}

class Detection {
  Detection({
    required this.label,
    required this.confidence,
    required this.x1,
    required this.y1,
    required this.x2,
    required this.y2,
    this.personName,
  });

  factory Detection.fromJson(Map<String, dynamic> j) => Detection(
        label: j['label'] as String? ?? j['person_name'] as String? ?? '?',
        confidence: (j['confidence'] as num?)?.toDouble() ?? 0,
        x1: (j['x1'] as num?)?.toDouble() ?? 0,
        y1: (j['y1'] as num?)?.toDouble() ?? 0,
        x2: (j['x2'] as num?)?.toDouble() ?? 0,
        y2: (j['y2'] as num?)?.toDouble() ?? 0,
        personName: j['person_name'] as String?,
      );

  final String label;
  final double confidence;
  final double x1, y1, x2, y2;
  final String? personName;
}

class Observation {
  Observation({
    required this.id,
    required this.cameraId,
    required this.startedAt,
    this.endedAt,
    this.vlmDescription,
    this.thumbnailPath,
    this.objectDetections = const [],
    this.personDetections = const [],
  });

  factory Observation.fromJson(Map<String, dynamic> j) {
    List<Detection> dets(dynamic block, String key) {
      if (block is Map && block[key] is List) {
        return (block[key] as List)
            .whereType<Map>()
            .map((d) => Detection.fromJson(d.cast<String, dynamic>()))
            .toList();
      }
      return const [];
    }

    return Observation(
      id: j['id'] as String,
      cameraId: j['camera_id'] as String? ?? '',
      startedAt: _date(j['started_at']) ?? DateTime.now(),
      endedAt: _date(j['ended_at']),
      vlmDescription: j['vlm_description'] as String?,
      thumbnailPath: j['thumbnail_path'] as String?,
      objectDetections: dets(j['object_detections'], 'detections'),
      personDetections: dets(j['person_detections'], 'persons'),
    );
  }

  final String id;
  final String cameraId;
  final DateTime startedAt;
  final DateTime? endedAt;
  final String? vlmDescription;
  final String? thumbnailPath;
  final List<Detection> objectDetections;
  final List<Detection> personDetections;

  List<String> get labels =>
      objectDetections.map((d) => d.label).toSet().toList();
}

class Event {
  Event({
    required this.id,
    required this.ruleId,
    required this.ruleName,
    required this.firedAt,
    this.actionStatus,
    this.actionType,
    this.observationId,
    this.recordingId,
    this.ackedAt,
    this.severity,
  });

  factory Event.fromJson(Map<String, dynamic> j) => Event(
        id: j['id'] as String,
        ruleId: j['rule_id'] as String? ?? '',
        ruleName: j['rule_name'] as String? ?? 'Rule',
        firedAt: _date(j['fired_at']) ?? DateTime.now(),
        actionStatus: j['action_status'] as String?,
        actionType: j['action_type'] as String?,
        observationId: j['observation_id'] as String?,
        recordingId: j['recording_id'] as String?,
        ackedAt: _date(j['acked_at']),
        severity: j['severity'] as String?,
      );

  final String id;
  final String ruleId;
  final String ruleName;
  final DateTime firedAt;
  final String? actionStatus;
  final String? actionType;
  final String? observationId;
  final String? recordingId;
  final DateTime? ackedAt;
  final String? severity;

  bool get acked => ackedAt != null;
}

class Rule {
  Rule({
    required this.id,
    required this.name,
    required this.enabled,
    required this.triggerPattern,
    required this.conditions,
    required this.actions,
    this.cooldownSeconds,
    this.snoozedUntil,
  });

  factory Rule.fromJson(Map<String, dynamic> j) => Rule(
        id: j['id'] as String,
        name: j['name'] as String? ?? 'Rule',
        enabled: j['enabled'] as bool? ?? true,
        triggerPattern:
            (j['trigger_pattern'] as Map?)?.cast<String, dynamic>() ?? {},
        conditions: (j['conditions'] as Map?)?.cast<String, dynamic>() ?? {},
        actions: (j['actions'] as List?)
                ?.whereType<Map>()
                .map((a) => a.cast<String, dynamic>())
                .toList() ??
            [],
        cooldownSeconds: j['cooldown_seconds'] as int?,
        snoozedUntil: _date(j['snoozed_until']),
      );

  final String id;
  final String name;
  final bool enabled;
  final Map<String, dynamic> triggerPattern;
  final Map<String, dynamic> conditions;
  final List<Map<String, dynamic>> actions;
  final int? cooldownSeconds;
  final DateTime? snoozedUntil;

  bool get snoozed =>
      snoozedUntil != null && snoozedUntil!.isAfter(DateTime.now());
}

class Person {
  Person({
    required this.id,
    required this.displayName,
    this.relationship,
    this.photoPath,
    this.sightings1h,
    this.sightings24h,
    this.sightingsTotal,
    this.lastSeenAt,
  });

  factory Person.fromJson(Map<String, dynamic> j) => Person(
        id: j['id'] as String? ?? j['person_id'] as String,
        displayName: j['display_name'] as String? ?? 'Unknown',
        relationship: j['relationship'] as String?,
        photoPath: j['photo_path'] as String?,
        sightings1h: j['sightings_1h'] as int?,
        sightings24h: j['sightings_24h'] as int?,
        sightingsTotal: j['sightings_total'] as int?,
        lastSeenAt: _date(j['last_seen_at']),
      );

  final String id;
  final String displayName;
  final String? relationship;
  final String? photoPath;
  final int? sightings1h;
  final int? sightings24h;
  final int? sightingsTotal;
  final DateTime? lastSeenAt;
}

class FaceClusterSuggestion {
  FaceClusterSuggestion({
    required this.id,
    required this.sightingCount,
    this.autoLabel,
    this.appearanceDescription,
    this.firstSeenAt,
    this.lastSeenAt,
  });

  factory FaceClusterSuggestion.fromJson(Map<String, dynamic> j) =>
      FaceClusterSuggestion(
        id: j['id'] as String,
        sightingCount: j['sighting_count'] as int? ?? 0,
        autoLabel: j['auto_label'] as String?,
        appearanceDescription: j['appearance_description'] as String?,
        firstSeenAt: _date(j['first_seen_at']),
        lastSeenAt: _date(j['last_seen_at']),
      );

  final String id;
  final int sightingCount;
  final String? autoLabel;
  final String? appearanceDescription;
  final DateTime? firstSeenAt;
  final DateTime? lastSeenAt;
}

class Recording {
  Recording({
    required this.id,
    required this.cameraId,
    required this.startedAt,
    this.endedAt,
    this.durationSeconds,
    this.fileSizeBytes,
  });

  factory Recording.fromJson(Map<String, dynamic> j) => Recording(
        id: j['id'] as String,
        cameraId: j['camera_id'] as String? ?? '',
        startedAt: _date(j['started_at']) ?? DateTime.now(),
        endedAt: _date(j['ended_at']),
        durationSeconds: (j['duration_seconds'] as num?)?.toDouble(),
        fileSizeBytes: j['file_size_bytes'] as int?,
      );

  final String id;
  final String cameraId;
  final DateTime startedAt;
  final DateTime? endedAt;
  final double? durationSeconds;
  final int? fileSizeBytes;
}

class AppNotification {
  AppNotification({
    required this.id,
    required this.title,
    required this.body,
    required this.createdAt,
    required this.read,
    this.eventId,
  });

  factory AppNotification.fromJson(Map<String, dynamic> j) => AppNotification(
        id: j['id'] as String,
        title: j['title'] as String? ?? '',
        body: j['body'] as String? ?? j['message'] as String? ?? '',
        createdAt: _date(j['created_at']) ?? DateTime.now(),
        read: j['read'] as bool? ?? j['read_at'] != null,
        eventId: j['event_id'] as String?,
      );

  final String id;
  final String title;
  final String body;
  final DateTime createdAt;
  final bool read;
  final String? eventId;
}

class TimelineItem {
  TimelineItem({
    required this.kind,
    required this.id,
    required this.cameraId,
    required this.startedAt,
    this.text,
    this.thumbnailPath,
    this.observation,
  });

  factory TimelineItem.fromJson(Map<String, dynamic> j) {
    final kind = j['kind'] as String? ?? 'observation';
    return TimelineItem(
      kind: kind,
      id: j['id'] as String,
      cameraId: j['camera_id'] as String? ?? '',
      startedAt: _date(j['started_at']) ?? DateTime.now(),
      text: j['text'] as String? ?? j['vlm_description'] as String?,
      thumbnailPath: j['thumbnail_path'] as String?,
      observation: kind == 'observation' ? Observation.fromJson(j) : null,
    );
  }

  final String kind; // observation | transcript
  final String id;
  final String cameraId;
  final DateTime startedAt;
  final String? text;
  final String? thumbnailPath;
  final Observation? observation;
}

class SystemStatus {
  SystemStatus({
    required this.version,
    required this.camerasTotal,
    required this.camerasOnline,
    required this.camerasRecording,
    this.uptimeSeconds,
  });

  factory SystemStatus.fromJson(Map<String, dynamic> j) => SystemStatus(
        version: j['version'] as String? ?? '?',
        camerasTotal: j['cameras_total'] as int? ?? 0,
        camerasOnline: j['cameras_online'] as int? ?? 0,
        camerasRecording: j['cameras_recording'] as int? ?? 0,
        uptimeSeconds: (j['uptime_seconds'] as num?)?.toDouble(),
      );

  final String version;
  final int camerasTotal;
  final int camerasOnline;
  final int camerasRecording;
  final double? uptimeSeconds;
}
