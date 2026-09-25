from services.api.routes.cameras import _activity_detection_flags


def test_activity_person_channel_accepts_body_and_track_detections_without_faces():
    assert _activity_detection_flags({"bodies": [{"bbox": [1, 2, 3, 4]}]}, None) == (True, False)
    assert _activity_detection_flags({"tracks": [{"track_id": "t1"}]}, None) == (True, False)


def test_activity_person_channel_accepts_yolo_person_and_keeps_named_faces_separate():
    assert _activity_detection_flags({}, {"objects": [{"label": "person"}]}) == (True, False)
    assert _activity_detection_flags({"faces": []}, {"objects": [{"label": "person"}]}) == (True, False)


def test_activity_object_channel_ignores_person_and_license_plate_labels():
    assert _activity_detection_flags({}, {"objects": [{"label": "car"}]}) == (False, True)
    assert _activity_detection_flags({}, {"objects": [{"label": "license_plate"}]}) == (False, False)
    assert _activity_detection_flags({}, {"objects": [{"label": "person"}, {"label": "car"}]}) == (True, True)
