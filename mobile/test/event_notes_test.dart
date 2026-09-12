import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/features/events/event_notes.dart';

void main() {
  test('every offered mute duration is inside the server bounds', () {
    // POST /api/events/{id}/mute accepts duration_seconds 60..86400.
    // A chip outside that range would be a button that always 422s.
    for (final (d, _) in kMuteChoices) {
      expect(d.inSeconds, greaterThanOrEqualTo(60), reason: d.toString());
      expect(d.inSeconds, lessThanOrEqualTo(86400), reason: d.toString());
    }
  });

  test('mute choices are offered shortest first', () {
    final secs = [for (final (d, _) in kMuteChoices) d.inSeconds];
    expect(secs, [...secs]..sort());
  });
}
