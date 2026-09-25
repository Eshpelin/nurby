"""Event payloads never leak filesystem paths (#301)."""

from datetime import datetime, timezone
from uuid import uuid4

from shared.schemas.observations import EventResponse


def test_event_response_removes_nested_filesystem_paths():
    event = EventResponse.model_validate({
        "id": uuid4(),
        "rule_id": None,
        "observation_id": None,
        "recording_id": None,
        "fired_at": datetime.now(timezone.utc),
        "payload": {
            "thumbnail_path": "/srv/nurby/private.jpg",
            "nested": {"clean_frame_path": "/tmp/frame.jpg", "label": "person"},
        },
        "acknowledged_at": None,
        "action_status": "success",
        "action_error": None,
        "action_type": "notify",
    })
    assert event.payload == {"nested": {"label": "person"}}
