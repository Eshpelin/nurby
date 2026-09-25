from shared.models import Camera
from shared.schemas import CameraCreate


def test_new_camera_schema_defaults_to_bounded_retention():
    camera = CameraCreate(name="Front Door", stream_url="rtsp://camera/stream")
    assert camera.retention_mode == "time"
    assert camera.retention_days == 30


def test_camera_model_default_is_bounded_retention():
    assert Camera.__table__.columns["retention_mode"].default.arg == "time"
