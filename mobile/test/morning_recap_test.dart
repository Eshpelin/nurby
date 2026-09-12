import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/features/timeline/morning_recap_card.dart';

void main() {
  group('factsSummary', () {
    test('a day with nothing in it says so rather than rendering blank', () {
      expect(factsSummary(const {}), 'A quiet day.');
    });

    test('lists what happened, in the order that matters at a glance', () {
      expect(
        factsSummary(const {
          'visitors': ['Sam', 'Alex'],
          'unknown_visitors': 1,
          'packages': 1,
          'vehicles': 2,
          'incidents_count': 3,
          'rule_fires': ['a'],
        }),
        '2 visitors, 1 unknown, 1 package, 2 vehicles, 3 incidents, 1 alert',
      );
    });

    test('singular and plural are right', () {
      expect(factsSummary(const {'visitors': ['Sam']}), '1 visitor');
      expect(factsSummary(const {'packages': 2}), '2 packages');
    });

    test('zero counts are omitted, not printed as "0 packages"', () {
      expect(factsSummary(const {'packages': 0, 'vehicles': 1}), '1 vehicle');
    });
  });
}
