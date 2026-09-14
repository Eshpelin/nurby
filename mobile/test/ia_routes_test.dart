import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/app.dart';
import 'package:nurby_mobile/features/activity/activity_screen.dart';

void main() {
  group('legacy /more paths resolve to their new home', () {
    // Anything bookmarked, deep-linked from a push, or in a stale
    // notification payload must still land somewhere sensible.
    test('activity kinds become filters', () {
      expect(legacyMorePath('incidents'), '/activity?kind=incidents');
      expect(legacyMorePath('journeys'), '/activity?kind=journeys');
      expect(legacyMorePath('conversations'), '/activity?kind=conversations');
      expect(legacyMorePath('digests'), '/activity?kind=recaps');
      expect(legacyMorePath('recordings'), '/activity?kind=recordings');
    });

    test('people and vehicles move to the People tab, keeping subpaths', () {
      expect(legacyMorePath('people'), '/people');
      expect(legacyMorePath('people/follow/person/p1'), '/people/follow/person/p1');
      expect(legacyMorePath('vehicles'), '/people/vehicles');
    });

    test('the old settings screen is now the general section', () {
      expect(legacyMorePath('settings'), '/settings/general');
    });

    test('everything else lives under /settings unchanged', () {
      expect(legacyMorePath('rules'), '/settings/rules');
      expect(legacyMorePath('rules/abc/edit'), '/settings/rules/abc/edit');
      expect(legacyMorePath('guardian/admin'), '/settings/guardian/admin');
      expect(legacyMorePath('shares'), '/settings/shares');
      expect(legacyMorePath('access'), '/settings/access');
    });
  });

  group('ActivityKind', () {
    test('slugs round-trip and unknown falls back to All', () {
      for (final k in ActivityKind.values) {
        expect(ActivityKind.fromSlug(k.slug), k);
      }
      expect(ActivityKind.fromSlug('nonsense'), ActivityKind.all);
      expect(ActivityKind.fromSlug(null), ActivityKind.all);
    });

    test('every kind has a label that is not the enum name', () {
      for (final k in ActivityKind.values) {
        expect(k.label, isNot(k.name));
      }
    });
  });
}
