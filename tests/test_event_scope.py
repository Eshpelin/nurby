from types import SimpleNamespace
from uuid import uuid4

from shared.camera_access import ALL
from services.api.routes.events import _event_in_scope


def test_batch_ack_scope_allows_admin_or_all_camera_access():
    camera_id = uuid4()
    event = SimpleNamespace(camera_id=camera_id)

    assert _event_in_scope(event, ALL)


def test_batch_ack_scope_rejects_foreign_and_camera_less_events():
    allowed_camera = uuid4()
    foreign_event = SimpleNamespace(camera_id=uuid4())
    camera_less_event = SimpleNamespace(camera_id=None)

    assert _event_in_scope(foreign_event, {allowed_camera}) is False
    assert _event_in_scope(camera_less_event, {allowed_camera}) is False


def test_batch_ack_scope_allows_selected_camera():
    camera_id = uuid4()

    assert _event_in_scope(SimpleNamespace(camera_id=camera_id), {camera_id})
