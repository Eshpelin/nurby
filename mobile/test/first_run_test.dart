import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/features/home/first_run_card.dart';

void main() {
  group('showFirstRun', () {
    test('shows on a fresh install', () {
      expect(showFirstRun(cameras: 0, rules: 0, dismissed: false), isTrue);
    });

    test('still shows with a camera but no rule', () {
      // This is the step that matters. A household with a camera and no
      // rule has a system that watches and never tells them anything.
      expect(showFirstRun(cameras: 1, rules: 0, dismissed: false), isTrue);
    });

    test('shows with rules but no camera', () {
      expect(showFirstRun(cameras: 0, rules: 3, dismissed: false), isTrue);
    });

    test('goes away once there is a camera and a rule', () {
      expect(showFirstRun(cameras: 1, rules: 1, dismissed: false), isFalse);
    });

    test('dismissing wins even on a fresh install', () {
      expect(showFirstRun(cameras: 0, rules: 0, dismissed: true), isFalse);
    });
  });
}
