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

/// A share link the current user created (list/manage view). The raw token
/// is never included here; it is returned exactly once at creation time.
class ShareLink {
  ShareLink({
    required this.id,
    required this.kind,
    required this.viewCount,
    required this.createdAt,
    required this.status,
    this.label,
    this.maxViews,
    this.expiresAt,
    this.revokedAt,
    this.lastAccessedAt,
  });

  factory ShareLink.fromJson(Map<String, dynamic> j) => ShareLink(
        id: j['id'] as String,
        kind: j['kind'] as String? ?? '?',
        label: j['label'] as String?,
        maxViews: j['max_views'] as int?,
        viewCount: j['view_count'] as int? ?? 0,
        expiresAt: _date(j['expires_at']),
        revokedAt: _date(j['revoked_at']),
        createdAt: _date(j['created_at']) ?? DateTime.now(),
        lastAccessedAt: _date(j['last_accessed_at']),
        status: j['status'] as String? ?? 'active',
      );

  final String id;
  final String kind; // recording | observation | event
  final String? label;
  final int? maxViews;
  final int viewCount;
  final DateTime? expiresAt;
  final DateTime? revokedAt;
  final DateTime createdAt;
  final DateTime? lastAccessedAt;
  final String status; // active | expired | revoked | exhausted
}

/// Creation response: carries the public URL (with the raw token) exactly once.
class CreatedShare {
  CreatedShare({
    required this.id,
    required this.url,
    required this.kind,
    this.expiresAt,
    this.maxViews,
  });

  factory CreatedShare.fromJson(Map<String, dynamic> j) => CreatedShare(
        id: j['id'] as String,
        url: j['url'] as String? ?? '',
        kind: j['kind'] as String? ?? '?',
        expiresAt: _date(j['expires_at']),
        maxViews: j['max_views'] as int?,
      );

  final String id;
  final String url;
  final String kind;
  final DateTime? expiresAt;
  final int? maxViews;
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

/// A cluster of repeat sightings of the same subject on one camera.
///
/// The backend groups observations into incidents so a person pacing in
/// front of a door is one thing to look at rather than forty.
class Incident {
  Incident({
    required this.id,
    required this.cameraId,
    required this.signatureKind,
    required this.signatureKey,
    required this.startedAt,
    required this.lastSeenAt,
    this.endedAt,
    this.finalized = false,
    this.occurrenceCount = 0,
    this.summaryText,
    this.thumbnails = const [],
    this.peakObservationId,
  });

  factory Incident.fromJson(Map<String, dynamic> j) => Incident(
        id: j['id'] as String,
        cameraId: j['camera_id'] as String? ?? '',
        signatureKind: j['signature_kind'] as String? ?? 'motion',
        signatureKey: j['signature_key'] as String? ?? '',
        startedAt: _date(j['started_at']) ?? DateTime.now(),
        lastSeenAt: _date(j['last_seen_at']) ?? DateTime.now(),
        endedAt: _date(j['ended_at']),
        finalized: j['finalized'] as bool? ?? false,
        occurrenceCount: (j['occurrence_count'] as num?)?.toInt() ?? 0,
        summaryText: j['summary_text'] as String?,
        thumbnails: (j['thumbnails'] as List? ?? [])
            .whereType<Map>()
            .map((t) => t.cast<String, dynamic>())
            .toList(),
        peakObservationId: j['peak_observation_id'] as String?,
      );

  final String id;
  final String cameraId;

  /// person | cluster | body | object | unknown | motion. Decides how the
  /// key should be read: a name, an id, or a label.
  final String signatureKind;
  final String signatureKey;
  final DateTime startedAt;
  final DateTime lastSeenAt;
  final DateTime? endedAt;
  final bool finalized;
  final int occurrenceCount;
  final String? summaryText;
  final List<Map<String, dynamic>> thumbnails;
  final String? peakObservationId;

  Duration get duration => lastSeenAt.difference(startedAt);
}

/// One subject's path across cameras.
class Journey {
  Journey({
    required this.id,
    required this.subjectKind,
    required this.subjectKey,
    required this.startedAt,
    required this.lastSeenAt,
    this.endedAt,
    this.finalized = false,
    this.camerasSeenCount = 0,
    this.incidentsCount = 0,
    this.summaryText,
    this.segments = const [],
  });

  factory Journey.fromJson(Map<String, dynamic> j) => Journey(
        id: j['id'] as String,
        subjectKind: j['subject_kind'] as String? ?? 'person',
        subjectKey: j['subject_key'] as String? ?? '',
        startedAt: _date(j['started_at']) ?? DateTime.now(),
        lastSeenAt: _date(j['last_seen_at']) ?? DateTime.now(),
        endedAt: _date(j['ended_at']),
        finalized: j['finalized'] as bool? ?? false,
        camerasSeenCount: (j['cameras_seen_count'] as num?)?.toInt() ?? 0,
        incidentsCount: (j['incidents_count'] as num?)?.toInt() ?? 0,
        summaryText: j['summary_text'] as String?,
        segments: (j['segments'] as List? ?? [])
            .whereType<Map>()
            .map((s) => s.cast<String, dynamic>())
            .toList(),
      );

  final String id;
  final String subjectKind;
  final String subjectKey;
  final DateTime startedAt;
  final DateTime lastSeenAt;
  final DateTime? endedAt;
  final bool finalized;
  final int camerasSeenCount;
  final int incidentsCount;
  final String? summaryText;
  final List<Map<String, dynamic>> segments;

  /// Camera names in the order the subject passed them, deduplicated so
  /// pacing between two rooms does not read as a ten-camera journey.
  List<String> get cameraPath {
    final out = <String>[];
    for (final s in segments) {
      final name = s['camera_name'] as String?;
      if (name != null && name.isNotEmpty && (out.isEmpty || out.last != name)) {
        out.add(name);
      }
    }
    return out;
  }
}

/// A stretch of speech near a camera, grouped from transcripts.
class Conversation {
  Conversation({
    required this.id,
    required this.cameraId,
    required this.startedAt,
    required this.endedAtProvisional,
    this.endedAt,
    this.transcriptCount = 0,
    this.finalized = false,
    this.summaryText,
    this.cleanedText,
    this.speakersSeen = const [],
    this.hasClip = false,
  });

  factory Conversation.fromJson(Map<String, dynamic> j) => Conversation(
        id: j['id'] as String,
        cameraId: j['camera_id'] as String? ?? '',
        startedAt: _date(j['started_at']) ?? DateTime.now(),
        endedAtProvisional:
            _date(j['ended_at_provisional']) ?? DateTime.now(),
        endedAt: _date(j['ended_at']),
        transcriptCount: (j['transcript_count'] as num?)?.toInt() ?? 0,
        finalized: j['finalized'] as bool? ?? false,
        summaryText: j['summary_text'] as String?,
        cleanedText: j['cleaned_text'] as String?,
        speakersSeen: (j['speakers_seen'] as List? ?? [])
            .map((s) => s.toString())
            .toList(),
        hasClip: j['has_clip'] as bool? ?? false,
      );

  final String id;
  final String cameraId;
  final DateTime startedAt;
  final DateTime endedAtProvisional;
  final DateTime? endedAt;
  final int transcriptCount;
  final bool finalized;
  final String? summaryText;
  final String? cleanedText;
  final List<String> speakersSeen;
  final bool hasClip;
}

/// One line of speech inside a conversation.
class ConversationTranscript {
  ConversationTranscript({
    required this.id,
    required this.startedAt,
    required this.text,
    this.speakerName,
  });

  factory ConversationTranscript.fromJson(Map<String, dynamic> j) =>
      ConversationTranscript(
        id: j['id'] as String,
        startedAt: _date(j['started_at']) ?? DateTime.now(),
        text: j['text'] as String? ?? '',
        speakerName: j['speaker_name'] as String?,
      );

  final String id;
  final DateTime startedAt;
  final String text;
  final String? speakerName;
}

/// A periodic written summary of what a camera saw.
class DigestEntry {
  DigestEntry({
    required this.id,
    required this.period,
    required this.summary,
    required this.generatedAt,
    this.cameraId,
    this.highlights = const [],
    this.totalObservations = 0,
  });

  factory DigestEntry.fromJson(Map<String, dynamic> j) => DigestEntry(
        id: j['id'] as String,
        period: j['period'] as String? ?? '',
        summary: j['summary'] as String? ?? '',
        generatedAt: _date(j['generated_at']) ?? DateTime.now(),
        cameraId: j['camera_id'] as String?,
        highlights:
            (j['highlights'] as List? ?? []).map((h) => h.toString()).toList(),
        totalObservations: (j['total_observations'] as num?)?.toInt() ?? 0,
      );

  final String id;
  final String period;
  final String summary;
  final DateTime generatedAt;

  /// Null means the digest covers every camera.
  final String? cameraId;
  final List<String> highlights;
  final int totalObservations;
}
