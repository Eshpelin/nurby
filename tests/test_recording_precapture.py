"""Pre/post-capture (Frigate's pre_capture / post_capture) for record-on-trigger modes.

Nurby applied the configurable recording_clip_pre / recording_clip_post only in
`clip` mode; `on_motion` / `on_object` had no pre-roll and used hardcoded
post-roll constants. These tests pin the post-roll wiring (the pre-roll flush
lives in the frame loop and needs a live capture, so it is covered by the loop's
structure rather than a unit test).
"""

import time
import uuid

from services.ingestion.stream import MOTION_THRESHOLD, StreamWorker


def _worker(mode: str, clip_post: int = 10, clip_pre: int = 5) -> StreamWorker:
    return StreamWorker(
        camera_id=uuid.uuid4(),
        stream_url="rtsp://example/stream",
        recording_enabled=True,
        recording_mode=mode,
        recording_clip_pre=clip_pre,
        recording_clip_post=clip_post,
    )


def test_config_fields_are_stored():
    w = _worker("on_motion", clip_post=7, clip_pre=3)
    assert w.recording_clip_pre == 3
    assert w.recording_clip_post == 7


def test_on_motion_post_roll_uses_configured_seconds():
    # A motion frame opens a post-roll window of recording_clip_post seconds,
    # NOT the old hardcoded 10s constant.
    w = _worker("on_motion", clip_post=7)
    before = time.monotonic()
    assert w._should_record(MOTION_THRESHOLD + 0.5) is True
    # end time should be ~now + 7s (allow scheduling slack).
    assert 6.5 <= (w._motion_end_time - before) <= 7.5


def test_on_motion_keeps_recording_during_post_roll_then_stops():
    w = _worker("on_motion", clip_post=5)
    w._should_record(MOTION_THRESHOLD + 0.5)  # open the window
    # Still inside the post-roll window with no new motion.
    assert w._should_record(None) is True
    # Force the window to have elapsed.
    w._motion_end_time = time.monotonic() - 0.01
    assert w._should_record(None) is False


def test_below_threshold_motion_does_not_open_window():
    w = _worker("on_motion", clip_post=5)
    # Sub-threshold motion must not (re)open the recording window.
    assert w._should_record(MOTION_THRESHOLD - 0.001) is False
    assert w._motion_end_time == 0


def test_always_and_off_modes_unaffected():
    assert _worker("always")._should_record(None) is True
    assert _worker("off")._should_record(MOTION_THRESHOLD + 1) is False
