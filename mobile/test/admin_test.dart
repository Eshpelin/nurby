import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/features/admin/admin_screens.dart';

void main() {
  group('accessSummary', () {
    test('zero grants means everything, and says so', () {
      // The policy in shared/camera_access.py: no grants is the
      // single-owner no-op and the user sees every camera. Rendering
      // "0 of 5 cameras" here would say the opposite of the truth.
      expect(accessSummary(0, 5), 'Sees every camera (5). No allowlist.');
    });

    test('one grant is an allowlist, not "one more camera"', () {
      expect(accessSummary(1, 5), 'Allowlist: 1 of 5 cameras.');
    });
  });
}
