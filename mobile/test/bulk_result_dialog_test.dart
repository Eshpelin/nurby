import 'package:flutter_test/flutter_test.dart';

import 'package:nurby_mobile/core/repositories.dart';

void main() {
  test('bulk result preserves mixed-success detail for the UI', () {
    final result = BulkDeleteResult.fromJson({
      'resource': 'recordings',
      'requested': 8,
      'deleted': 5,
      'missing': 1,
      'skipped': 1,
      'failed': 1,
      'failed_ids': ['recording-7'],
    });

    expect(result.deleted, 5);
    expect(result.missing, 1);
    expect(result.skipped, 1);
    expect(result.failed, 1);
    expect(result.failedIds, ['recording-7']);
  });
}
