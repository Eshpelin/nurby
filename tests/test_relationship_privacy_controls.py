"""Per-camera inference privacy controls (#256)."""

from shared.models import Camera
from shared.schemas import CameraCreate, CameraResponse, CameraUpdate


def test_relationship_privacy_controls_default_to_conservative_enabled_behavior():
    created = CameraCreate(name="Front door", stream_url="rtsp://camera/stream")
    assert created.relationship_inference_enabled is True
    assert created.relationship_notifications_enabled is True
    assert created.vehicle_relationship_inference_enabled is True
    assert created.cooccurrence_inference_enabled is True
    assert created.name_mention_inference_enabled is True

    updated = CameraUpdate(
        relationship_inference_enabled=False,
        relationship_notifications_enabled=False,
        vehicle_relationship_inference_enabled=False,
        cooccurrence_inference_enabled=False,
        name_mention_inference_enabled=False,
    )
    assert updated.model_dump(exclude_unset=True) == {
        "relationship_inference_enabled": False,
        "relationship_notifications_enabled": False,
        "vehicle_relationship_inference_enabled": False,
        "cooccurrence_inference_enabled": False,
        "name_mention_inference_enabled": False,
    }
    assert "relationship_inference_enabled" in CameraResponse.model_fields
    assert "relationship_notifications_enabled" in CameraResponse.model_fields
    assert "vehicle_relationship_inference_enabled" in CameraResponse.model_fields
    assert "cooccurrence_inference_enabled" in CameraResponse.model_fields
    assert "name_mention_inference_enabled" in CameraResponse.model_fields
    assert hasattr(Camera, "relationship_inference_enabled")
    assert hasattr(Camera, "relationship_notifications_enabled")
    assert hasattr(Camera, "vehicle_relationship_inference_enabled")
    assert hasattr(Camera, "cooccurrence_inference_enabled")
    assert hasattr(Camera, "name_mention_inference_enabled")
