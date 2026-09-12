"""Personas are one list served to both clients; the split between camera
and audio fields has to match what each endpoint actually accepts."""
from shared.camera_personas import AUDIO_FIELDS, CAMERA_PERSONAS, split_patch
from shared.schemas import CameraUpdate


def test_six_personas_with_stable_ids():
    assert [p["id"] for p in CAMERA_PERSONAS] == [
        "front-door", "baby-cam", "pet-cam", "wildlife", "driveway", "traffic",
    ]


def test_every_camera_field_is_accepted_by_camera_update():
    # A persona field CameraUpdate does not know would be silently dropped
    # by the PATCH, so the persona would look applied and not be.
    accepted = set(CameraUpdate.model_fields)
    for p in CAMERA_PERSONAS:
        camera, _ = split_patch(p["patch"])
        unknown = set(camera) - accepted
        assert not unknown, f"{p['id']}: CameraUpdate does not accept {sorted(unknown)}"


def test_audio_fields_are_exactly_the_ones_camera_update_lacks():
    accepted = set(CameraUpdate.model_fields)
    assert not (AUDIO_FIELDS & accepted), "an AUDIO_FIELD is also on CameraUpdate; the split is wrong"


def test_split_is_a_partition():
    for p in CAMERA_PERSONAS:
        camera, audio = split_patch(p["patch"])
        assert set(camera) | set(audio) == set(p["patch"])
        assert not (set(camera) & set(audio))


def test_personas_endpoint_is_reachable_by_literal_path():
    from fastapi.testclient import TestClient

    from services.api.main import app
    from shared.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: object()
    try:
        r = TestClient(app).get("/api/cameras/personas")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    # 422 here would mean "personas" was parsed as a camera uuid.
    assert r.status_code == 200, r.text
    assert len(r.json()["personas"]) == 6
