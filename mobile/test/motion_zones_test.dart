import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/core/theme.dart';
import 'package:nurby_mobile/features/cameras/motion_zones_section.dart';

void main() {
  test('every zone type the pipeline knows has a label', () {
    for (final t in ['zone', 'include', 'exclude', 'loiter', 'tripwire', 'veto', 'signal']) {
      expect(zoneTypeLabel(t), isNot(t), reason: t);
    }
  });

  test('an unknown type falls back to itself rather than blank', () {
    expect(zoneTypeLabel('future-kind'), 'future-kind');
    expect(zoneTypeLabel(null), 'Zone');
  });

  test('exclusions and vetoes read as danger, tripwires as warning', () {
    // Colour is the only cue on the frame overlay. A red exclusion next
    // to a green include must not be the same colour.
    expect(zoneColor('exclude'), NurbyColors.danger);
    expect(zoneColor('veto'), NurbyColors.danger);
    expect(zoneColor('tripwire'), NurbyColors.warning);
    expect(zoneColor('include'), NurbyColors.accent);
    expect(zoneColor('exclude'), isNot(zoneColor('include')));
  });
}
