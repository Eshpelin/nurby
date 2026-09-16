import 'package:dio/dio.dart';

import 'api_client.dart';
import 'outbox.dart';
import '../models/models.dart';
import '../models/household_mode.dart';

/// One repository per API resource group. Thin: shape mapping only,
/// no caching (Riverpod providers own lifecycle).
class AuthRepository {
  AuthRepository(this._api);
  final ApiClient _api;

  Future<bool> needsSetup() async {
    final j = await _api.getJson('/api/auth/needs-setup') as Map;
    return j['needs_setup'] as bool? ?? false;
  }

  Future<(String token, User user)> login(String email, String password) async {
    final j = await _api.postJson('/api/auth/login',
        body: {'email': email, 'password': password}) as Map<String, dynamic>;
    return (
      j['access_token'] as String,
      User.fromJson(j['user'] as Map<String, dynamic>)
    );
  }

  Future<(String token, User user)> setup(
      String email, String displayName, String password) async {
    final j = await _api.postJson('/api/auth/setup', body: {
      'email': email,
      'display_name': displayName,
      'password': password,
    }) as Map<String, dynamic>;
    return (
      j['access_token'] as String,
      User.fromJson(j['user'] as Map<String, dynamic>)
    );
  }

  Future<(String token, User user)> register(String email, String displayName,
      String password, String inviteKey) async {
    final j = await _api.postJson('/api/auth/register', body: {
      'email': email,
      'display_name': displayName,
      'password': password,
      'invite_key': inviteKey,
    }) as Map<String, dynamic>;
    return (
      j['access_token'] as String,
      User.fromJson(j['user'] as Map<String, dynamic>)
    );
  }

  /// Exchange a scanned QR pairing code for an access token.
  Future<(String token, User user)> pairClaim(String code) async {
    final j = await _api.postJson('/api/auth/pair/claim',
        body: {'code': code}) as Map<String, dynamic>;
    return (
      j['access_token'] as String,
      User.fromJson(j['user'] as Map<String, dynamic>)
    );
  }

  Future<User> me() async =>
      User.fromJson(await _api.getJson('/api/auth/me') as Map<String, dynamic>);
}

class CameraRepository {
  CameraRepository(this._api);
  final ApiClient _api;

  Future<List<Camera>> list() async {
    final j = await _api.getJson('/api/cameras', query: {'limit': 100}) as List;
    return j
        .whereType<Map>()
        .map((c) => Camera.fromJson(c.cast<String, dynamic>()))
        .toList();
  }

  Future<Camera> get(String id) async => Camera.fromJson(
      await _api.getJson('/api/cameras/$id') as Map<String, dynamic>);

  Future<Camera> create(Map<String, dynamic> body) async => Camera.fromJson(
      await _api.postJson('/api/cameras', body: body) as Map<String, dynamic>);

  Future<Camera> update(String id, Map<String, dynamic> patch) async =>
      Camera.fromJson(await _api.patchJson('/api/cameras/$id', body: patch)
          as Map<String, dynamic>);

  Future<void> remove(String id) => _api.delete('/api/cameras/$id');

  /// Audio and transcription config lives on its own endpoint, not on the
  /// camera PATCH. It is admin-only and every field in the body is
  /// privacy-relevant, so the backend writes an AudioAuditLog row for each
  /// flip. Sending these through the camera PATCH instead would silently
  /// skip that audit trail, so this stays a separate call on purpose.
  Future<Map<String, dynamic>> updateAudio(
          String id, Map<String, dynamic> patch) async =>
      (await _api.patchJson('/api/audio/cameras/$id/audio', body: patch) as Map)
          .cast<String, dynamic>();

  Future<Camera> createDemo() async => Camera.fromJson(
      await _api.postJson('/api/cameras/demo') as Map<String, dynamic>);

  /// Scan for ONVIF cameras.
  ///
  /// The scan runs on the Nurby server, not on this device: it is
  /// WS-Discovery multicast from the API process. So it finds what the
  /// server can see, which is not necessarily what the phone can see, and
  /// it needs no local-network permission from the phone.
  Future<List<Map<String, dynamic>>> discover({int timeout = 5}) async {
    final j = await _api.getJson('/api/cameras/discover',
        query: {'timeout': timeout}) as List;
    return j.whereType<Map>().map((d) => d.cast<String, dynamic>()).toList();
  }

  /// Persist the order cameras appear in.
  Future<void> reorder(List<String> orderedIds) => _api.postJson(
        '/api/cameras/reorder',
        body: [
          for (var i = 0; i < orderedIds.length; i++)
            {'id': orderedIds[i], 'display_order': i},
        ],
      );

  Future<Map<String, dynamic>> testConnection(Map<String, dynamic> body) async =>
      (await _api.postJson('/api/cameras/test-connection', body: body) as Map)
          .cast<String, dynamic>();

  Future<List<Detection>> liveDetections(String id) async {
    final j = await _api.getJson('/api/cameras/$id/live-detections') as Map;
    return (j['detections'] as List? ?? [])
        .whereType<Map>()
        .map((d) => Detection.fromJson(d.cast<String, dynamic>()))
        .toList();
  }

  /// Latest cached frame (webcam/snapshot cameras). Poll for live-ish view.
  String frameUrl(String id) => _api.mediaUrl('/api/cameras/$id/frame');
}

class ObservationRepository {
  ObservationRepository(this._api);
  final ApiClient _api;

  Future<List<Observation>> list({
    String? cameraId,
    String? personId,
    String? label,
    DateTime? from,
    DateTime? to,
    int limit = 50,
    int offset = 0,
  }) async {
    final j = await _api.getJson('/api/observations', query: {
      if (cameraId != null) 'camera_id': cameraId,
      if (personId != null) 'person_id': personId,
      if (label != null) 'label': label,
      if (from != null) 'from': from.toUtc().toIso8601String(),
      if (to != null) 'to': to.toUtc().toIso8601String(),
      'limit': limit,
      'offset': offset,
    }) as List;
    return j
        .whereType<Map>()
        .map((o) => Observation.fromJson(o.cast<String, dynamic>()))
        .toList();
  }

  Future<Observation> get(String id) async => Observation.fromJson(
      await _api.getJson('/api/observations/$id') as Map<String, dynamic>);

  String thumbnailUrl(String id) =>
      _api.mediaUrl('/api/observations/$id/thumbnail');
}

class TimelineRepository {
  TimelineRepository(this._api);
  final ApiClient _api;

  Future<List<TimelineItem>> list({
    String? cameraId,
    DateTime? from,
    DateTime? to,
    int limit = 50,
    int offset = 0,
  }) async {
    final res = await _api.getJson('/api/timeline', query: {
      if (cameraId != null) 'camera_id': cameraId,
      if (from != null) 'from': from.toUtc().toIso8601String(),
      if (to != null) 'to': to.toUtc().toIso8601String(),
      'limit': limit,
      'offset': offset,
    });
    // Timeline responds {items: [...], total_seen} unlike sibling endpoints.
    final j = res is Map ? (res['items'] as List? ?? []) : res as List;
    return j
        .whereType<Map>()
        .map((t) => TimelineItem.fromJson(t.cast<String, dynamic>()))
        .toList();
  }
}

class EventRepository {
  EventRepository(this._api, {MutationOutbox? outbox}) : _outbox = outbox;
  final ApiClient _api;
  final MutationOutbox? _outbox;

  Future<List<Event>> history({
    String? cameraId,
    String? ruleId,
    bool? acked,
    DateTime? from,
    DateTime? to,
    int limit = 50,
    int offset = 0,
  }) async {
    final j = await _api.getJson('/api/events/history', query: {
      if (cameraId != null) 'camera_id': cameraId,
      if (ruleId != null) 'rule_id': ruleId,
      if (acked != null) 'acked': acked,
      if (from != null) 'from': from.toUtc().toIso8601String(),
      if (to != null) 'to': to.toUtc().toIso8601String(),
      'limit': limit,
      'offset': offset,
    }) as List;
    return j
        .whereType<Map>()
        .map((e) => Event.fromJson(e.cast<String, dynamic>()))
        .toList();
  }

  Future<int> unreviewedCount() async {
    final j = await _api.getJson('/api/events/count') as Map;
    return j['unreviewed_count'] as int? ?? 0;
  }

  /// Offline-safe: on a connectivity failure the ack is queued in the
  /// outbox for later replay, then the error is rethrown so callers can
  /// show a "queued" message.
  Future<Event> acknowledge(String id) async {
    final path = '/api/events/$id/ack';
    try {
      return Event.fromJson(
          await _api.postJson(path) as Map<String, dynamic>);
    } on DioException catch (e) {
      await _maybeEnqueue(e, path);
      rethrow;
    }
  }

  /// Offline-safe, see [acknowledge].
  Future<int> batchAck(List<String> ids) async {
    const path = '/api/events/batch-ack';
    final body = {'event_ids': ids};
    try {
      final j = await _api.postJson(path, body: body) as Map;
      return j['updated'] as int? ?? 0;
    } on DioException catch (e) {
      await _maybeEnqueue(e, path, body: body);
      rethrow;
    }
  }

  /// Mute: stop telling me about this one for a while. Offline-safe like
  /// ack, and more important to be: on a phone, where the alert actually
  /// arrives, "stop telling me" is the action someone reaches for in a
  /// dead zone. The duration rides in the query string, which the outbox
  /// replays as part of the path.
  Future<Event> mute(String id, {Duration duration = const Duration(minutes: 10)}) async {
    final secs = duration.inSeconds.clamp(60, 86400);
    final path = '/api/events/$id/mute?duration_seconds=$secs';
    try {
      return Event.fromJson(await _api.postJson(path) as Map<String, dynamic>);
    } on DioException catch (e) {
      await _maybeEnqueue(e, path);
      rethrow;
    }
  }

  Future<List<Map<String, dynamic>>> notes(String id) async {
    final j = await _api.getJson('/api/events/$id/notes') as List;
    return j.whereType<Map>().map((n) => n.cast<String, dynamic>()).toList();
  }

  /// Offline-safe, see [acknowledge]. A note written in a dead zone is
  /// still a note the household meant to keep.
  Future<Map<String, dynamic>> addNote(String id, String text) async {
    final path = '/api/events/$id/notes';
    final body = {'text': text};
    try {
      return (await _api.postJson(path, body: body) as Map)
          .cast<String, dynamic>();
    } on DioException catch (e) {
      await _maybeEnqueue(e, path, body: body);
      rethrow;
    }
  }

  Future<void> deleteNote(String eventId, String noteId) =>
      _api.delete('/api/events/$eventId/notes/$noteId');

  Future<void> _maybeEnqueue(DioException e, String path,
      {Object? body}) async {
    if (_outbox == null || !isConnectivityError(e)) return;
    await _outbox.enqueue(method: 'POST', path: path, body: body);
  }
}

class RuleRepository {
  RuleRepository(this._api);
  final ApiClient _api;

  /// Starter rules for the first-run flow. Data from the backend, so
  /// mobile offers the same four as web without a copy of the template
  /// library.
  Future<List<Map<String, dynamic>>> starters() async {
    final j = await _api.getJson('/api/rules/starters') as Map;
    return (j['starters'] as List? ?? const [])
        .whereType<Map>()
        .map((s) => s.cast<String, dynamic>())
        .toList();
  }

  /// One tap: the server builds the rule and saves it.
  Future<Map<String, dynamic>> createFromStarter(String key, {String? cameraId}) async =>
      (await _api.postJson('/api/rules/starters', body: {
        'key': key,
        if (cameraId != null) 'camera_id': cameraId,
      }) as Map)
          .cast<String, dynamic>();

  Future<List<Rule>> list() async {
    final j = await _api.getJson('/api/rules') as List;
    return j
        .whereType<Map>()
        .map((r) => Rule.fromJson(r.cast<String, dynamic>()))
        .toList();
  }

  Future<Map<String, dynamic>> schema() async =>
      (await _api.getJson('/api/rules/schema') as Map).cast<String, dynamic>();

  Future<Rule> create(Map<String, dynamic> body) async => Rule.fromJson(
      await _api.postJson('/api/rules', body: body) as Map<String, dynamic>);

  Future<Rule> update(String id, Map<String, dynamic> patch) async =>
      Rule.fromJson(await _api.patchJson('/api/rules/$id', body: patch)
          as Map<String, dynamic>);

  Future<void> remove(String id) => _api.delete('/api/rules/$id');

  Future<Rule> snooze(String id, int seconds) async => Rule.fromJson(
      await _api.postJson('/api/rules/$id/snooze', body: {'seconds': seconds})
          as Map<String, dynamic>);

  Future<Rule> unsnooze(String id) async => Rule.fromJson(
      await _api.postJson('/api/rules/$id/unsnooze') as Map<String, dynamic>);

  /// Natural-language rule generation.
  Future<Map<String, dynamic>> generate(String prompt) async =>
      (await _api.postJson('/api/rules/generate', body: {'prompt': prompt})
              as Map)
          .cast<String, dynamic>();
}

/// Household mode (#184). One value for the whole house that rules gate on.
class HouseholdRepository {
  HouseholdRepository(this._api);
  final ApiClient _api;

  Future<HouseholdModeState> mode() async => HouseholdModeState.fromJson(
      (await _api.getJson('/api/household/mode') as Map).cast<String, dynamic>());

  Future<HouseholdModeState> setMode(String mode, {String? note}) async =>
      HouseholdModeState.fromJson((await _api.putJson('/api/household/mode',
              body: {'mode': mode, if (note != null) 'note': note}) as Map)
          .cast<String, dynamic>());
}

class PersonRepository {
  PersonRepository(this._api);
  final ApiClient _api;

  Future<List<Person>> list() async {
    final j = await _api.getJson('/api/persons') as List;
    return j
        .whereType<Map>()
        .map((p) => Person.fromJson(p.cast<String, dynamic>()))
        .toList();
  }

  Future<List<Person>> activitySummary() async {
    final j = await _api.getJson('/api/persons/activity/summary') as List;
    return j
        .whereType<Map>()
        .map((p) => Person.fromJson(p.cast<String, dynamic>()))
        .toList();
  }

  Future<Person> create(String displayName, {String? relationship}) async =>
      Person.fromJson(await _api.postJson('/api/persons', body: {
        'display_name': displayName,
        if (relationship != null) 'relationship': relationship,
      }) as Map<String, dynamic>);

  Future<Person> update(String id, Map<String, dynamic> patch) async =>
      Person.fromJson(await _api.patchJson('/api/persons/$id', body: patch)
          as Map<String, dynamic>);

  Future<List<FaceClusterSuggestion>> suggestions() async {
    final j = await _api.getJson('/api/persons/suggestions') as List;
    return j
        .whereType<Map>()
        .map((s) => FaceClusterSuggestion.fromJson(s.cast<String, dynamic>()))
        .toList();
  }

  Future<void> nameCluster(String clusterId, String displayName,
      {String? relationship}) async {
    await _api.postJson('/api/persons/suggestions/$clusterId/name', body: {
      'display_name': displayName,
      if (relationship != null) 'relationship': relationship,
    });
  }

  // --- issue #171 -----------------------------------------------------

  /// Fold [sourceId] into [targetId]. The target survives; the source's
  /// sightings, faces and history move across and the source is gone.
  /// Not reversible, which the UI has to say in those words.
  Future<Person> merge({required String targetId, required String sourceId}) async =>
      Person.fromJson((await _api.postJson('/api/persons/$targetId/merge',
              body: {'source_id': sourceId}) as Map)
          .cast<String, dynamic>());

  /// Add a face sample from an image on this device.
  Future<void> addFace(String personId, String filePath) async {
    final form = FormData.fromMap({
      'file': await MultipartFile.fromFile(filePath),
    });
    await _api.dio.post<dynamic>('/api/persons/$personId/face', data: form);
  }

  /// Real sightings a person's photo could be set from.
  Future<List<Map<String, dynamic>>> photoCandidates(String personId) async {
    final j = await _api.getJson('/api/persons/$personId/photo-candidates') as List;
    return j.whereType<Map>().map((c) => c.cast<String, dynamic>()).toList();
  }

  Future<void> setPhotoFromObservation(String personId, String observationId) =>
      _api.postJson('/api/persons/$personId/photo-from-observation',
          body: {'observation_id': observationId});

  Future<void> ignoreCluster(String clusterId) async {
    await _api.postJson('/api/persons/suggestions/$clusterId/ignore');
  }

  String clusterThumbnailUrl(String clusterId) =>
      _api.mediaUrl('/api/persons/suggestions/$clusterId/thumbnail');
}

class SearchRepository {
  SearchRepository(this._api);
  final ApiClient _api;

  Future<List<Observation>> search(String query,
      {String? cameraId, int limit = 30}) async {
    final j = await _api.getJson('/api/search', query: {
      'q': query,
      if (cameraId != null) 'camera_id': cameraId,
      'limit': limit,
    }) as Map;
    return (j['results'] as List? ?? [])
        .whereType<Map>()
        .map((o) => Observation.fromJson(o.cast<String, dynamic>()))
        .toList();
  }

  Future<Map<String, dynamic>> ask(String question) async =>
      (await _api.postJson('/api/search/ask', body: {'question': question})
              as Map)
          .cast<String, dynamic>();

  Future<Map<String, dynamic>> digest({String period = 'daily'}) async =>
      (await _api.getJson('/api/search/digest', query: {'period': period})
              as Map)
          .cast<String, dynamic>();
}

class RecordingRepository {
  RecordingRepository(this._api);
  final ApiClient _api;

  Future<List<Recording>> list({
    String? cameraId,
    DateTime? from,
    DateTime? to,
    int limit = 50,
    int offset = 0,
  }) async {
    final j = await _api.getJson('/api/recordings', query: {
      if (cameraId != null) 'camera_id': cameraId,
      if (from != null) 'from': from.toUtc().toIso8601String(),
      if (to != null) 'to': to.toUtc().toIso8601String(),
      'limit': limit,
      'offset': offset,
    }) as List;
    return j
        .whereType<Map>()
        .map((r) => Recording.fromJson(r.cast<String, dynamic>()))
        .toList();
  }

  String streamUrl(String id) => _api.mediaUrl('/api/recordings/$id/stream');

  String thumbnailUrl(String id) =>
      _api.mediaUrl('/api/recordings/$id/thumbnail');

  /// Per-recording activity: object classes, named people, vehicles, and
  /// whether it carried speech. One call for a page of ids rather than
  /// one per row, which is what makes the list scannable rather than a
  /// column of identical play buttons.
  Future<Map<String, Map<String, dynamic>>> facets(List<String> ids) async {
    if (ids.isEmpty) return const {};
    // The server caps a request at 200 ids.
    final j = await _api.getJson('/api/recordings/facets',
        query: {'ids': ids.take(200).join(',')}) as Map;
    return {
      for (final e in j.entries)
        '${e.key}': (e.value as Map).cast<String, dynamic>(),
    };
  }

  /// A downloadable URL for the whole file, or a clip of it. Both carry
  /// the media token, since whatever saves the file cannot send headers.
  String downloadUrl(String id) =>
      _api.mediaUrl('/api/recordings/$id/download');

  // mediaUrl replaces the query string wholesale when it adds the token,
  // so start and end go in as params rather than baked into the path.
  String clipUrl(String id, {required Duration start, required Duration end}) =>
      _api.mediaUrl('/api/recordings/$id/clip', {
        'start': '${start.inSeconds}',
        'end': '${end.inSeconds}',
      });
}

class ShareRepository {
  ShareRepository(this._api);
  final ApiClient _api;

  /// Create an anonymous scoped share link. [expirySeconds] is rounded UP to
  /// whole days because the backend's granularity is days (min 1, max 30), so
  /// a "1 hour" choice becomes a 1-day link.
  Future<CreatedShare> create({
    required String kind, // recording | observation | event
    required String resourceId,
    required int expirySeconds,
    int? maxViews,
    String? label,
  }) async {
    final days = (expirySeconds / Duration.secondsPerDay).ceil().clamp(1, 30);
    final j = await _api.postJson('/api/shares', body: {
      'kind': kind,
      'resource_id': resourceId,
      'expires_in_days': days,
      if (maxViews != null) 'max_views': maxViews,
      if (label != null) 'label': label,
    }) as Map<String, dynamic>;
    return CreatedShare.fromJson(j);
  }

  /// Share links I created (admins see everyone's).
  Future<List<ShareLink>> listMine() async {
    final j = await _api.getJson('/api/shares') as List;
    return j
        .whereType<Map>()
        .map((s) => ShareLink.fromJson(s.cast<String, dynamic>()))
        .toList();
  }

  /// Kill a link immediately. Idempotent server-side.
  Future<ShareLink> revoke(String id) async => ShareLink.fromJson(
      await _api.postJson('/api/shares/$id/revoke') as Map<String, dynamic>);
}

class NotificationRepository {
  NotificationRepository(this._api, {MutationOutbox? outbox})
      : _outbox = outbox;
  final ApiClient _api;
  final MutationOutbox? _outbox;

  Future<List<AppNotification>> list({bool unreadOnly = false}) async {
    final j = await _api.getJson('/api/notifications', query: {
      if (unreadOnly) 'unread_only': true,
      'limit': 50,
    }) as List;
    return j
        .whereType<Map>()
        .map((n) => AppNotification.fromJson(n.cast<String, dynamic>()))
        .toList();
  }

  Future<int> unreadCount() async {
    final j = await _api.getJson('/api/notifications/count') as Map;
    return j['unread'] as int? ?? 0;
  }

  /// Offline-safe: queued in the outbox on connectivity failures, then
  /// rethrown so callers can show a "queued" message.
  Future<void> markRead(String id) async {
    final path = '/api/notifications/$id/read';
    try {
      await _api.patchJson(path);
    } on DioException catch (e) {
      if (_outbox != null && isConnectivityError(e)) {
        await _outbox.enqueue(method: 'PATCH', path: path);
      }
      rethrow;
    }
  }

  Future<void> markAllRead() async {
    await _api.postJson('/api/notifications/read-all');
  }
}

class SystemRepository {
  SystemRepository(this._api);
  final ApiClient _api;

  Future<SystemStatus> status() async => SystemStatus.fromJson(
      await _api.getJson('/api/status') as Map<String, dynamic>);

  Future<Map<String, dynamic>> health() async =>
      (await _api.getJson('/api/health') as Map).cast<String, dynamic>();

  Future<List<Map<String, dynamic>>> doctor() async {
    final j = await _api.getJson('/api/system/doctor');
    final items = j is List ? j : (j as Map)['checks'] as List? ?? [];
    return items.whereType<Map>().map((c) => c.cast<String, dynamic>()).toList();
  }

  Future<Map<String, dynamic>> storage() async =>
      (await _api.getJson('/api/storage') as Map).cast<String, dynamic>();
}

/// Camera voice: live conversations, taking over, and speaking.
///
/// The doorstep case is the one that matters on a phone. Somebody is at
/// a camera, a push arrives, and the household wants to see what is
/// being said and say something back without opening a laptop.
class VoiceRepository {
  VoiceRepository(this._api);
  final ApiClient _api;

  /// Conversations still open. At most one per camera, and usually zero.
  Future<List<Map<String, dynamic>>> liveSessions() async {
    final j = await _api.getJson('/api/voice/sessions',
        query: {'active': true, 'limit': 5});
    final items = (j as Map)['sessions'] as List? ?? [];
    return items.whereType<Map>().map((s) => s.cast<String, dynamic>()).toList();
  }

  /// One exchange with both halves of the conversation interleaved.
  Future<Map<String, dynamic>> session(String id) async =>
      (await _api.getJson('/api/voice/sessions/$id') as Map)
          .cast<String, dynamic>();

  /// Take the conversation. The camera stops answering immediately.
  Future<Map<String, dynamic>> takeOver(String id) async =>
      (await _api.postJson('/api/voice/sessions/$id/handoff') as Map)
          .cast<String, dynamic>();

  /// Say something in your own words. Not run through the disclosure
  /// filter: that exists to stop a model leaking the household's
  /// information, not to police what a household says to its own
  /// visitor.
  Future<Map<String, dynamic>> say(String id, String text) async =>
      (await _api.postJson('/api/voice/sessions/$id/say',
              body: {'text': text}) as Map)
          .cast<String, dynamic>();

  // --- Configuration (issue #159) -------------------------------------
  //
  // Every endpoint below is admin-only server-side.

  /// Household voice settings, plus the disclosure key catalogue and the
  /// list of things no setting can ever unlock.
  Future<Map<String, dynamic>> settings() async =>
      (await _api.getJson('/api/voice/settings') as Map)
          .cast<String, dynamic>();

  /// The PATCH body is not symmetric with the GET: the allowlist reads
  /// back as `voice_may_confirm` and `voice_never_say` but is written as
  /// `may_confirm` and `never_say`. Callers pass the write names.
  Future<Map<String, dynamic>> updateSettings(
          Map<String, dynamic> patch) async =>
      (await _api.patchJson('/api/voice/settings', body: patch) as Map)
          .cast<String, dynamic>();

  /// The intents a household picks between, in offer order.
  Future<List<Map<String, dynamic>>> presets() async {
    final j = await _api.getJson('/api/voice/presets') as Map;
    return (j['presets'] as List? ?? [])
        .whereType<Map>()
        .map((p) => p.cast<String, dynamic>())
        .toList();
  }

  /// What the configured TTS provider can produce. `enumerable` is false
  /// for providers whose voices are model files rather than a list, so
  /// the UI offers free text instead of pretending to enumerate them.
  Future<Map<String, dynamic>> voices() async =>
      (await _api.getJson('/api/voice/voices') as Map).cast<String, dynamic>();

  /// One camera's voice config, including whether its hardware was ever
  /// probed. Never probed and probed-but-unsupported are different states.
  Future<Map<String, dynamic>> camera(String cameraId) async =>
      (await _api.getJson('/api/voice/cameras/$cameraId') as Map)
          .cast<String, dynamic>();

  /// Apply a preset, explicit fields, or both in one request. The preset
  /// lands first and explicit fields override it.
  Future<Map<String, dynamic>> updateCamera(
          String cameraId, Map<String, dynamic> patch) async =>
      (await _api.patchJson('/api/voice/cameras/$cameraId', body: patch) as Map)
          .cast<String, dynamic>();

  /// Say a test phrase through the real path. Not a simulation and not
  /// exempt from the guards, so it can legitimately come back refused
  /// during quiet hours.
  Future<Map<String, dynamic>> test(String cameraId) async =>
      (await _api.postJson('/api/voice/cameras/$cameraId/test') as Map)
          .cast<String, dynamic>();
}

/// Body clusters: appearance-based suggestions (issue #171).
///
/// Mirrors the face-cluster flow but built from body embeddings, so it
/// works when a face was never seen. A tentative cluster is body-only;
/// a confirmed one was co-verified by a face on the same frame.
class BodyClusterRepository {
  BodyClusterRepository(this._api);
  final ApiClient _api;

  Future<List<Map<String, dynamic>>> suggestions() async {
    final j = await _api.getJson('/api/body-clusters/suggestions') as List;
    return j.whereType<Map>().map((c) => c.cast<String, dynamic>()).toList();
  }

  String thumbnailUrl(String clusterId) =>
      _api.mediaUrl('/api/body-clusters/suggestions/$clusterId/thumbnail');

  Future<void> name(String clusterId, String displayName, {String? relationship}) =>
      _api.postJson('/api/body-clusters/suggestions/$clusterId/name', body: {
        'display_name': displayName,
        if (relationship != null && relationship.isNotEmpty)
          'relationship': relationship,
      });

  /// Attach to a person who already exists rather than creating one.
  Future<void> link(String clusterId, String personId) =>
      _api.postJson('/api/body-clusters/suggestions/$clusterId/link',
          body: {'person_id': personId});

  Future<void> ignore(String clusterId) =>
      _api.postJson('/api/body-clusters/suggestions/$clusterId/ignore');
}

/// Scheduled reports: saved Ask questions on a clock.
class ReportRepository {
  ReportRepository(this._api);
  final ApiClient _api;

  Future<List<ScheduledReport>> list() async {
    final j = await _api.getJson('/api/reports') as List;
    return j
        .whereType<Map>()
        .map((r) => ScheduledReport.fromJson(r.cast<String, dynamic>()))
        .toList();
  }

  Future<ScheduledReport> create(Map<String, dynamic> body) async =>
      ScheduledReport.fromJson(
          (await _api.postJson('/api/reports', body: body) as Map)
              .cast<String, dynamic>());

  Future<ScheduledReport> update(String id, Map<String, dynamic> patch) async =>
      ScheduledReport.fromJson(
          (await _api.patchJson('/api/reports/$id', body: patch) as Map)
              .cast<String, dynamic>());

  Future<void> remove(String id) => _api.delete('/api/reports/$id');

  /// Run it now, inline, and get the report back with last_output set.
  /// This is what makes the builder usable: a question can be tried
  /// before it is trusted to a schedule.
  Future<ScheduledReport> run(String id) async => ScheduledReport.fromJson(
      (await _api.postJson('/api/reports/$id/run') as Map)
          .cast<String, dynamic>());
}

/// Guardian: what a guardian may see about one dependant.
///
/// Every read here is capability-gated server-side and answers 403 when
/// the link's tier does not include it. That is a normal state, not an
/// error: a guardian on the alerts-only tier is meant to be told what
/// their tier covers, not shown a failure.
class GuardianRepository {
  GuardianRepository(this._api);
  final ApiClient _api;

  /// Alert kinds, delivery channels and tier labels, from the backend.
  /// These used to be hardcoded in Dart beside a copy in Python; a ninth
  /// alert kind would have appeared in neither client.
  Future<Map<String, dynamic>> vocabulary() async =>
      (await _api.getJson('/api/guardian/vocabulary') as Map)
          .cast<String, dynamic>();

  Future<List<Map<String, dynamic>>> links() async {
    final j = await _api.getJson('/api/guardian/me') as Map;
    return (j['links'] as List? ?? [])
        .whereType<Map>()
        .map((l) => l.cast<String, dynamic>())
        .toList();
  }

  Future<Map<String, dynamic>> status(String linkId) async =>
      (await _api.getJson('/api/guardian/links/$linkId/status') as Map)
          .cast<String, dynamic>();

  /// Wellbeing rollup: did they eat, did they fall, what happened this
  /// week. Best-effort signals, never a medical guarantee, and the UI
  /// should not imply otherwise.
  Future<Map<String, dynamic>> wellbeing(String linkId) async =>
      (await _api.getJson('/api/guardian/links/$linkId/wellbeing') as Map)
          .cast<String, dynamic>();

  Future<Map<String, dynamic>> trends(String linkId, {int days = 7}) async =>
      (await _api.getJson('/api/guardian/links/$linkId/trends',
              query: {'days': days}) as Map)
          .cast<String, dynamic>();

  Future<Map<String, dynamic>> events(String linkId, {int limit = 30}) async =>
      (await _api.getJson('/api/guardian/links/$linkId/events',
              query: {'limit': limit}) as Map)
          .cast<String, dynamic>();

  Future<Map<String, dynamic>> actions(String linkId,
          {int limit = 50, String? action}) async =>
      (await _api.getJson('/api/guardian/links/$linkId/actions', query: {
        'limit': limit,
        if (action != null) 'action': action,
      }) as Map)
          .cast<String, dynamic>();

  Future<Map<String, dynamic>> updateAlerts(
          String linkId, Map<String, bool> prefs) async =>
      (await _api.patchJson('/api/guardian/links/$linkId/alerts',
              body: {'alert_prefs': prefs}) as Map)
          .cast<String, dynamic>();

  Future<Map<String, dynamic>> updateChannels(
          String linkId, Map<String, bool> channels) async =>
      (await _api.patchJson('/api/guardian/links/$linkId/channels',
              body: {'notify_channels': channels}) as Map)
          .cast<String, dynamic>();

  Future<List<Map<String, dynamic>>> notifications() async {
    final j = await _api.getJson('/api/guardian/notifications');
    final items = j is List ? j : (j as Map)['items'] as List? ?? [];
    return items.whereType<Map>().map((n) => n.cast<String, dynamic>()).toList();
  }

  Future<void> markNotificationRead(String id) =>
      _api.postJson('/api/guardian/notifications/$id/read');

  /// What is available to look at right now: presence, a recent still,
  /// a recent clip. The URLs it returns are relative and need the media
  /// token treatment, since native players cannot send headers.
  Future<Map<String, dynamic>> live(String linkId) async =>
      (await _api.getJson('/api/guardian/links/$linkId/live') as Map)
          .cast<String, dynamic>();

  String imageUrl(String linkId) =>
      _api.mediaUrl('/api/guardian/links/$linkId/image');

  String clipUrl(String linkId) =>
      _api.mediaUrl('/api/guardian/links/$linkId/clip');

  String photoUrl(String linkId) =>
      _api.mediaUrl('/api/guardian/links/$linkId/photo');

  /// Ask a question about this one dependant. Scoped to the link, so it
  /// cannot reach anything the tier does not already allow.
  Future<Map<String, dynamic>> search(String linkId, String query,
          {int limit = 20}) async =>
      (await _api.postJson('/api/guardian/links/$linkId/search',
              body: {'query': query, 'limit': limit}) as Map)
          .cast<String, dynamic>();

  /// People approved to collect a dependant.
  Future<List<Map<String, dynamic>>> pickups(String personId) async {
    final j = await _api
        .getJson('/api/guardian/persons/$personId/pickups') as List;
    return j.whereType<Map>().map((p) => p.cast<String, dynamic>()).toList();
  }

  Future<Map<String, dynamic>> addPickup(
    String personId, {
    required String name,
    required String kind,
    String? vehiclePlate,
    String? linkedPersonId,
  }) async =>
      (await _api.postJson('/api/guardian/persons/$personId/pickups', body: {
        'name': name,
        'kind': kind,
        if (vehiclePlate != null && vehiclePlate.isNotEmpty)
          'vehicle_plate': vehiclePlate,
        if (linkedPersonId != null) 'linked_person_id': linkedPersonId,
      }) as Map)
          .cast<String, dynamic>();

  Future<void> removePickup(String pickupId) =>
      _api.delete('/api/guardian/pickups/$pickupId');

  /// Consent to being watched. Withdrawing does not revoke existing
  /// links, which the UI has to say rather than imply.
  Future<Map<String, dynamic>> setConsent(String personId, bool given) async =>
      (await _api.postJson('/api/guardian/persons/$personId/consent',
              body: {'given': given}) as Map)
          .cast<String, dynamic>();

  /// Every read a guardian has made. The dependant's household can see
  /// who looked at what, which is the check on the whole feature.
  Future<List<Map<String, dynamic>>> accessLog(
      {String? personId, int limit = 100}) async {
    final j = await _api.getJson('/api/guardian/access-log', query: {
      'limit': limit,
      if (personId != null) 'person_id': personId,
    }) as List;
    return j.whereType<Map>().map((a) => a.cast<String, dynamic>()).toList();
  }

  Future<List<Map<String, dynamic>>> facilities() async {
    final j = await _api.getJson('/api/guardian/facilities') as List;
    return j.whereType<Map>().map((f) => f.cast<String, dynamic>()).toList();
  }

  Future<Map<String, dynamic>> createFacility(Map<String, dynamic> body) async =>
      (await _api.postJson('/api/guardian/facilities', body: body) as Map)
          .cast<String, dynamic>();

  Future<Map<String, dynamic>> updateFacility(
          String id, Map<String, dynamic> patch) async =>
      (await _api.patchJson('/api/guardian/facilities/$id', body: patch) as Map)
          .cast<String, dynamic>();

  /// Links the household has granted, as opposed to /me which is the
  /// links granted *to* the caller.
  Future<List<Map<String, dynamic>>> allLinks({String? personId}) async {
    final j = await _api.getJson('/api/guardian/links', query: {
      if (personId != null) 'person_id': personId,
    }) as List;
    return j.whereType<Map>().map((l) => l.cast<String, dynamic>()).toList();
  }

  Future<Map<String, dynamic>> createLink(Map<String, dynamic> body) async =>
      (await _api.postJson('/api/guardian/links', body: body) as Map)
          .cast<String, dynamic>();

  Future<void> revokeLink(String linkId) =>
      _api.delete('/api/guardian/links/$linkId');

  /// Redeem a guardian invite and activate the account.
  ///
  /// Unauthenticated by design: the magic-link token is the credential.
  /// The password is whatever the person claiming the invite types, so
  /// this is the one guardian call made before a session exists.
  Future<Map<String, dynamic>> claim({
    required String token,
    required String password,
    String? displayName,
  }) async =>
      (await _api.postJson('/api/guardian/claim', body: {
        'token': token,
        'password': password,
        if (displayName != null && displayName.isNotEmpty)
          'display_name': displayName,
      }) as Map)
          .cast<String, dynamic>();
}

/// Privacy zones: regions the pipeline blurs before anything else sees
/// the frame. Auto-zones are written by perception; this API only lets a
/// household turn one off, lock it so the auto refresh stops overwriting
/// its polygon, or delete it.
class PrivacyZoneRepository {
  PrivacyZoneRepository(this._api);
  final ApiClient _api;

  Future<List<Map<String, dynamic>>> list(String cameraId) async {
    final j = await _api.getJson('/api/privacy-zones',
        query: {'camera_id': cameraId}) as List;
    return j.whereType<Map>().map((z) => z.cast<String, dynamic>()).toList();
  }

  /// Labels the auto detector knows how to match. The picker is limited
  /// to these so nobody types a target the pipeline will silently ignore.
  Future<List<String>> targets() async {
    final j = await _api.getJson('/api/privacy-zones/targets') as List;
    return j.map((t) => t.toString()).toList();
  }

  Future<Map<String, dynamic>> update(
          String zoneId, Map<String, dynamic> patch) async =>
      (await _api.patchJson('/api/privacy-zones/$zoneId', body: patch) as Map)
          .cast<String, dynamic>();

  Future<void> remove(String zoneId) =>
      _api.delete('/api/privacy-zones/$zoneId');
}

/// Saved PTZ positions. A camera with presets can be sent to one by name,
/// which is the only way most people actually use PTZ.
class PtzRepository {
  PtzRepository(this._api);
  final ApiClient _api;

  Future<List<Map<String, dynamic>>> presets(String cameraId) async {
    final j = await _api.getJson('/api/cameras/$cameraId/ptz/presets') as List;
    return j.whereType<Map>().map((p) => p.cast<String, dynamic>()).toList();
  }

  Future<void> goto(String cameraId, String presetToken) => _api.postJson(
      '/api/cameras/$cameraId/ptz/goto',
      body: {'preset_token': presetToken});
}

/// The follow feed: everything about one subject, in one bundle.
///
/// A person and a cluster are different endpoints because they are keyed
/// differently, but the bundle they return has the same shape, so callers
/// get one type back either way.
class FollowRepository {
  FollowRepository(this._api);
  final ApiClient _api;

  Future<FollowBundle> person(String personId,
          {List<String> cameraIds = const [], int limit = 80}) =>
      _fetch('/api/persons/$personId/follow', cameraIds, limit);

  Future<FollowBundle> cluster(String clusterId,
          {List<String> cameraIds = const [], int limit = 80}) =>
      _fetch('/api/persons/clusters/$clusterId/follow', cameraIds, limit);

  Future<FollowBundle> _fetch(
      String path, List<String> cameraIds, int limit) async {
    final j = await _api.getJson(path, query: {
      'limit': limit,
      // Repeated camera_id params, which is what the endpoint's
      // list[uuid] Query expects. A comma-joined string would be read as
      // one malformed uuid.
      if (cameraIds.isNotEmpty) 'camera_id': cameraIds,
    }) as Map;
    return FollowBundle.fromJson(j.cast<String, dynamic>());
  }
}

/// Incidents: repeat sightings of one subject on one camera, grouped.
class IncidentRepository {
  IncidentRepository(this._api);
  final ApiClient _api;

  Future<List<Incident>> list({String? cameraId, bool? finalized, int limit = 50}) async {
    final j = await _api.getJson('/api/incidents', query: {
      'limit': limit,
      if (cameraId != null) 'camera_id': cameraId,
      if (finalized != null) 'finalized': finalized,
    }) as List;
    return j
        .whereType<Map>()
        .map((i) => Incident.fromJson(i.cast<String, dynamic>()))
        .toList();
  }

  Future<Incident> get(String id) async => Incident.fromJson(
      await _api.getJson('/api/incidents/$id') as Map<String, dynamic>);
}

/// Journeys: one subject's path across cameras.
class JourneyRepository {
  JourneyRepository(this._api);
  final ApiClient _api;

  Future<List<Journey>> list({bool? finalized, int limit = 50}) async {
    final j = await _api.getJson('/api/journeys', query: {
      'limit': limit,
      if (finalized != null) 'finalized': finalized,
    }) as List;
    return j
        .whereType<Map>()
        .map((x) => Journey.fromJson(x.cast<String, dynamic>()))
        .toList();
  }

  Future<Journey> get(String id) async => Journey.fromJson(
      await _api.getJson('/api/journeys/$id') as Map<String, dynamic>);
}

/// Conversations: speech near a camera, grouped from transcripts.
class ConversationRepository {
  ConversationRepository(this._api);
  final ApiClient _api;

  Future<List<Conversation>> list({String? cameraId, int limit = 50}) async {
    final j = await _api.getJson('/api/conversations', query: {
      'limit': limit,
      if (cameraId != null) 'camera_id': cameraId,
    }) as List;
    return j
        .whereType<Map>()
        .map((c) => Conversation.fromJson(c.cast<String, dynamic>()))
        .toList();
  }

  /// The conversation plus the lines it was built from. Only the detail
  /// endpoint carries transcripts, so the list stays cheap.
  Future<(Conversation, List<ConversationTranscript>)> get(String id) async {
    final j = (await _api.getJson('/api/conversations/$id') as Map)
        .cast<String, dynamic>();
    final lines = (j['transcripts'] as List? ?? [])
        .whereType<Map>()
        .map((t) => ConversationTranscript.fromJson(t.cast<String, dynamic>()))
        .toList();
    return (Conversation.fromJson(j), lines);
  }
}

/// Transcripts as records (issue #176): correct one, delete one, search
/// across them. Reading them stays inside ConversationRepository.
class TranscriptRepository {
  TranscriptRepository(this._api);
  final ApiClient _api;

  /// Fix what STT got wrong. The server keeps the original on first
  /// edit, so this is safe to expose: what was heard is not lost.
  Future<Map<String, dynamic>> correct(String id, String text) async =>
      (await _api.patchJson('/api/transcripts/$id', body: {'text': text}) as Map)
          .cast<String, dynamic>();

  /// Remove a line for good. A transcript is a recording of someone
  /// speaking near a house; being able to delete one is a privacy
  /// control, not a tidy-up.
  Future<void> remove(String id) => _api.delete('/api/transcripts/$id');

  Future<List<Map<String, dynamic>>> search(String query,
      {String? cameraId, int limit = 50}) async {
    final j = await _api.getJson('/api/transcripts', query: {
      'search': query,
      'limit': limit,
      if (cameraId != null) 'camera_id': cameraId,
    });
    final items = j is List ? j : (j as Map)['items'] as List? ?? const [];
    return items.whereType<Map>().map((t) => t.cast<String, dynamic>()).toList();
  }
}

/// Digests: periodic written summaries of what a camera saw.
class DigestRepository {
  DigestRepository(this._api);
  final ApiClient _api;

  Future<List<DigestEntry>> list({String? cameraId, int limit = 50}) async {
    final j = await _api.getJson('/api/digests', query: {
      'limit': limit,
      if (cameraId != null) 'camera_id': cameraId,
    }) as List;
    return j
        .whereType<Map>()
        .map((d) => DigestEntry.fromJson(d.cast<String, dynamic>()))
        .toList();
  }
}
