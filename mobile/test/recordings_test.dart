import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/core/api_client.dart';
import 'package:nurby_mobile/core/repositories.dart';

void main() {
  group('RecordingRepository urls', () {
    final api = ApiClient(baseUrl: 'http://h');
    final repo = RecordingRepository(api);

    test('clip bounds survive the token merge', () {
      // mediaUrl replaces the query string when it adds the token. If
      // start and end were baked into the path they would be dropped and
      // the server would 422 on a missing required param.
      final u = Uri.parse(repo.clipUrl('r1',
          start: const Duration(seconds: 5), end: const Duration(seconds: 65)));
      expect(u.path, '/api/recordings/r1/clip');
      expect(u.queryParameters['start'], '5');
      expect(u.queryParameters['end'], '65');
    });

    test('thumbnail and download point at their endpoints', () {
      expect(Uri.parse(repo.thumbnailUrl('r1')).path,
          '/api/recordings/r1/thumbnail');
      expect(Uri.parse(repo.downloadUrl('r1')).path,
          '/api/recordings/r1/download');
    });

    test('bulk bundle URL carries selected recording ids', () {
      final u = Uri.parse(repo.bundleUrl(ids: const ['r1', 'r2']));
      expect(u.path, '/api/recordings/download-bundle');
      expect(u.queryParametersAll['recording_id'], ['r1', 'r2']);
    });

    test('bulk preview and delete responses preserve safety details', () {
      final preview = BulkPreview.fromJson({
        'resource': 'recordings',
        'requested': 2,
        'matching': 1,
        'estimated_bytes': 2048,
        'cameras': ['c1'],
        'missing_files': 1,
      });
      final result = BulkDeleteResult.fromJson({
        'resource': 'recordings',
        'requested': 2,
        'deleted': 1,
        'skipped': 1,
        'failed_ids': [],
      });
      expect(preview.matching, 1);
      expect(preview.missingFiles, 1);
      expect(preview.cameras, ['c1']);
      expect(result.deleted, 1);
      expect(result.skipped, 1);
    });
  });

  test('facets is a no-op for an empty page', () async {
    final repo = RecordingRepository(ApiClient(baseUrl: 'http://h'));
    // No network call is made, so this resolves without a server.
    expect(await repo.facets(const []), isEmpty);
  });
}
