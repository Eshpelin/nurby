"""Tests for the MQTT topic contract (shared/mqtt_topics.py)."""

import uuid

from shared.mqtt_topics import (
    camera_command_topic,
    camera_events_topic,
    camera_motion_topic,
    camera_snapshot_topic,
    camera_slug,
    camera_state_topic,
    events_topic,
    parse_camera_command,
    stats_topic,
    status_topic,
)

CID = uuid.UUID("3f2ab123-0000-0000-0000-000000000000")


def test_camera_slug_readable_and_stable():
    assert camera_slug("Front Door", CID) == "front-door-3f2a"
    # Stable across calls, independent of name case/spacing.
    assert camera_slug("FRONT  door!", CID) == camera_slug("front door", CID)
    # Same name, different camera -> different slug.
    other = uuid.UUID("00000000-0000-0000-0000-000000009911")
    assert camera_slug("Front Door", other) != camera_slug("Front Door", CID)
    # Empty name still yields a usable segment.
    assert camera_slug("", CID) == f"camera-{str(CID)[:4]}"


def test_topic_builders_honor_prefix():
    slug = "front-door-3f2a"
    assert status_topic("nurby") == "nurby/status"
    assert stats_topic("home") == "home/stats"
    assert events_topic("nurby") == "nurby/events"
    assert camera_motion_topic(slug, "nurby") == "nurby/cameras/front-door-3f2a/motion"
    assert camera_events_topic(slug, "nurby") == "nurby/cameras/front-door-3f2a/events"
    assert camera_snapshot_topic(slug, "nurby") == "nurby/cameras/front-door-3f2a/snapshot"
    assert (
        camera_command_topic(slug, "detect", "nurby")
        == "nurby/cameras/front-door-3f2a/detect/set"
    )
    assert (
        camera_state_topic(slug, "recordings", "nurby")
        == "nurby/cameras/front-door-3f2a/recordings/state"
    )


def test_parse_camera_command_matches_only_set_topics():
    slug = "front-door-3f2a"
    assert parse_camera_command(f"nurby/cameras/{slug}/detect/set", "nurby") == (slug, "detect")
    # /state is our own echo, never a command.
    assert parse_camera_command(f"nurby/cameras/{slug}/detect/state", "nurby") is None
    # Wrong prefix, extra segments, unknown toggle, and unrelated trees.
    assert parse_camera_command(f"other/cameras/{slug}/detect/set", "nurby") is None
    assert parse_camera_command("nurby/cameras/detect/set", "nurby") is None
    assert parse_camera_command(f"nurby/cameras/{slug}/volume/set", "nurby") is None
    assert parse_camera_command("nurby/events", "nurby") is None


def test_camera_toggle_builders_reject_unknown_names():
    import pytest

    with pytest.raises(ValueError):
        camera_state_topic("s", "volume")
    with pytest.raises(ValueError):
        camera_command_topic("s", "motion")
