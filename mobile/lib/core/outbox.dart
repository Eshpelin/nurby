import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';

/// A queued mutation waiting for connectivity.
class OutboxEntry {
  OutboxEntry({
    required this.method,
    required this.path,
    this.body,
    DateTime? queuedAt,
  }) : queuedAt = queuedAt ?? DateTime.now().toUtc();

  factory OutboxEntry.fromJson(Map<String, dynamic> j) => OutboxEntry(
        method: j['method'] as String,
        path: j['path'] as String,
        body: j['body'],
        queuedAt: DateTime.tryParse(j['queued_at'] as String? ?? '') ??
            DateTime.now().toUtc(),
      );

  final String method;
  final String path;
  final Object? body;
  final DateTime queuedAt;

  Map<String, dynamic> toJson() => {
        'method': method,
        'path': path,
        'body': body,
        'queued_at': queuedAt.toIso8601String(),
      };
}

/// Persisted FIFO queue of mutations made while offline, replayed when
/// connectivity returns (see outboxDrainProvider in providers.dart).
///
/// Only used for mutations that are safe to replay late: event acks and
/// notification mark-read are idempotent server-side.
class MutationOutbox {
  MutationOutbox(this._prefs);

  static const prefsKey = 'mutation_outbox';
  static const maxEntries = 100;

  final SharedPreferences _prefs;
  bool _draining = false;

  List<OutboxEntry> load() {
    final raw = _prefs.getString(prefsKey);
    if (raw == null) return [];
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! List) return [];
      return decoded
          .whereType<Map>()
          .map((j) => OutboxEntry.fromJson(j.cast<String, dynamic>()))
          .toList();
    } catch (_) {
      // Corrupt payload: better to lose the queue than to crash forever.
      return [];
    }
  }

  int get length => load().length;

  Future<void> _save(List<OutboxEntry> entries) async {
    await _prefs.setString(
        prefsKey, jsonEncode([for (final e in entries) e.toJson()]));
  }

  /// Append a mutation. When full, the oldest entries are dropped so the
  /// most recent user actions win.
  Future<void> enqueue({
    required String method,
    required String path,
    Object? body,
  }) async {
    final entries = load()
      ..add(OutboxEntry(method: method, path: path, body: body));
    if (entries.length > maxEntries) {
      entries.removeRange(0, entries.length - maxEntries);
    }
    await _save(entries);
  }

  /// Replay queued mutations FIFO. Removes an entry on success or on any
  /// 4xx response (permanent failure, retrying would never succeed). Stops
  /// draining, keeping the remainder, on a connectivity-type failure.
  /// Returns the number of successfully replayed mutations.
  Future<int> drain(ApiClient api) async {
    if (_draining) return 0; // re-entrancy guard: one drain at a time
    _draining = true;
    try {
      var entries = load();
      var replayed = 0;
      while (entries.isNotEmpty) {
        final entry = entries.first;
        try {
          await _send(api, entry);
          replayed++;
        } on DioException catch (e) {
          if (isConnectivityError(e)) break; // still offline: try later
          final status = e.response?.statusCode ?? 0;
          if (status < 400 || status >= 500) break; // unknown/5xx: try later
          // 4xx: permanent failure, drop the entry and continue.
        }
        entries = entries.sublist(1);
        await _save(entries);
      }
      await _save(entries);
      return replayed;
    } finally {
      _draining = false;
    }
  }

  Future<void> _send(ApiClient api, OutboxEntry entry) {
    switch (entry.method.toUpperCase()) {
      case 'POST':
        return api.postJson(entry.path, body: entry.body);
      case 'PATCH':
        return api.patchJson(entry.path, body: entry.body);
      case 'DELETE':
        return api.delete(entry.path);
      default:
        // Unsupported method (never enqueued today): drop it via the 4xx
        // path by treating it as done.
        return Future.value();
    }
  }
}
