import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/core/api_client.dart';
import 'package:nurby_mobile/core/outbox.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Scripted ApiClient: each path resolves per [behaviors]
/// ('ok', 'offline', or an HTTP status code as a string).
class FakeApiClient extends ApiClient {
  FakeApiClient(this.behaviors) : super(baseUrl: 'http://fake');

  final Map<String, String> behaviors;
  final List<String> calls = [];

  Future<dynamic> _respond(String method, String path) {
    calls.add('$method $path');
    final behavior = behaviors[path] ?? 'ok';
    if (behavior == 'ok') return Future.value(<String, dynamic>{});
    final options = RequestOptions(path: path, method: method);
    if (behavior == 'offline') {
      throw DioException(
          requestOptions: options, type: DioExceptionType.connectionError);
    }
    final status = int.parse(behavior);
    throw DioException(
      requestOptions: options,
      type: DioExceptionType.badResponse,
      response: Response(requestOptions: options, statusCode: status),
    );
  }

  @override
  Future<dynamic> postJson(String path, {Object? body}) =>
      _respond('POST', path);

  @override
  Future<dynamic> patchJson(String path, {Object? body}) =>
      _respond('PATCH', path);

  @override
  Future<void> delete(String path) async => _respond('DELETE', path);
}

Future<MutationOutbox> makeOutbox() async {
  SharedPreferences.setMockInitialValues({});
  return MutationOutbox(await SharedPreferences.getInstance());
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('enqueue persists JSON entries under the mutation_outbox key', () async {
    final outbox = await makeOutbox();
    await outbox.enqueue(
        method: 'POST', path: '/api/events/e1/ack', body: {'x': 1});

    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(MutationOutbox.prefsKey);
    expect(raw, isNotNull);
    final decoded = jsonDecode(raw!) as List;
    expect(decoded, hasLength(1));
    final entry = decoded.first as Map;
    expect(entry['method'], 'POST');
    expect(entry['path'], '/api/events/e1/ack');
    expect(entry['body'], {'x': 1});
    expect(DateTime.tryParse(entry['queued_at'] as String), isNotNull);
  });

  test('drain replays FIFO and removes entries on success', () async {
    final outbox = await makeOutbox();
    await outbox.enqueue(method: 'POST', path: '/a');
    await outbox.enqueue(method: 'PATCH', path: '/b');
    await outbox.enqueue(method: 'POST', path: '/c');

    final api = FakeApiClient({});
    final replayed = await outbox.drain(api);

    expect(replayed, 3);
    expect(api.calls, ['POST /a', 'PATCH /b', 'POST /c']);
    expect(outbox.length, 0);
  });

  test('drain drops 4xx entries as permanent failures and continues',
      () async {
    final outbox = await makeOutbox();
    await outbox.enqueue(method: 'POST', path: '/gone');
    await outbox.enqueue(method: 'POST', path: '/fine');

    final api = FakeApiClient({'/gone': '404'});
    final replayed = await outbox.drain(api);

    expect(replayed, 1); // only /fine actually succeeded
    expect(api.calls, ['POST /gone', 'POST /fine']);
    expect(outbox.length, 0); // 404 entry dropped, not retried forever
  });

  test('drain stops on a connectivity failure and keeps the remainder',
      () async {
    final outbox = await makeOutbox();
    await outbox.enqueue(method: 'POST', path: '/first');
    await outbox.enqueue(method: 'POST', path: '/second');

    final api = FakeApiClient({'/first': 'offline'});
    final replayed = await outbox.drain(api);

    expect(replayed, 0);
    expect(api.calls, ['POST /first']); // never reached /second
    expect(outbox.length, 2); // nothing lost

    // Connectivity back: same queue drains fully.
    final apiOnline = FakeApiClient({});
    expect(await outbox.drain(apiOnline), 2);
    expect(outbox.length, 0);
  });

  test('drain keeps entries on 5xx (server hiccup, retry later)', () async {
    final outbox = await makeOutbox();
    await outbox.enqueue(method: 'POST', path: '/flaky');
    await outbox.enqueue(method: 'POST', path: '/after');

    final api = FakeApiClient({'/flaky': '503'});
    expect(await outbox.drain(api), 0);
    expect(outbox.length, 2);
  });

  test('cap: oldest entries are dropped beyond 100', () async {
    final outbox = await makeOutbox();
    for (var i = 0; i < 105; i++) {
      await outbox.enqueue(method: 'POST', path: '/m$i');
    }
    final entries = outbox.load();
    expect(entries, hasLength(MutationOutbox.maxEntries));
    expect(entries.first.path, '/m5'); // 0..4 dropped
    expect(entries.last.path, '/m104');
  });

  test('load survives corrupt persisted payloads', () async {
    SharedPreferences.setMockInitialValues(
        {MutationOutbox.prefsKey: 'not json ['});
    final outbox = MutationOutbox(await SharedPreferences.getInstance());
    expect(outbox.load(), isEmpty);
  });
}
