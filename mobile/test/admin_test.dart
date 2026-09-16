import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/features/admin/admin_screens.dart';

void main() {
  group('accessSummary', () {
    test('zero selected grants means no access', () {
      expect(accessSummary(0, 5), 'No camera access.');
    });
    test('only explicit all mode includes future cameras', () {
      expect(accessSummary(0, 5, mode: 'all'), 'Sees every camera (5), including future cameras.');
    });
    test('none ignores any stale grant count', () {
      expect(accessSummary(2, 5, mode: 'none'), 'No camera access.');
    });
    test('selected grants describe the effective selection', () {
      expect(accessSummary(1, 5), 'Selected: 1 of 5 cameras.');
    });
  });
}
