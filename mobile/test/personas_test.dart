import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/features/cameras/personas_section.dart';

void main() {
  test('splits a persona patch by the field list the server sent', () {
    // audio_* fields are not on CameraUpdate. Sending them to the camera
    // PATCH would be silently dropped, and the persona would look applied
    // while the camera stayed deaf.
    final r = splitPersonaPatch(
      {'detect_faces': false, 'audio_capture_enabled': true, 'vlm_trigger': 'on_object'},
      const ['audio_capture_enabled', 'audio_store_raw'],
    );
    expect(r.camera, {'detect_faces': false, 'vlm_trigger': 'on_object'});
    expect(r.audio, {'audio_capture_enabled': true});
  });

  test('an empty audio field list sends everything to the camera', () {
    final r = splitPersonaPatch({'a': 1, 'b': 2}, const []);
    expect(r.camera, {'a': 1, 'b': 2});
    expect(r.audio, isEmpty);
  });
}
