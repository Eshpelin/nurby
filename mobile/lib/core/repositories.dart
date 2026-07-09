import 'package:dio/dio.dart';

import 'api_client.dart';
import 'outbox.dart';
import '../models/models.dart';

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

  Future<Camera> createDemo() async => Camera.fromJson(
      await _api.postJson('/api/cameras/demo') as Map<String, dynamic>);

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

  Future<void> _maybeEnqueue(DioException e, String path,
      {Object? body}) async {
    if (_outbox == null || !isConnectivityError(e)) return;
    await _outbox.enqueue(method: 'POST', path: path, body: body);
  }
}

class RuleRepository {
  RuleRepository(this._api);
  final ApiClient _api;

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
