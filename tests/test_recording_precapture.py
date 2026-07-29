"""Pre/post-capture (Frigate's pre_capture / post_capture) for record-on-trigger modes.

Nurby applied the configurable recording_clip_pre / recording_clip_post only in
`clip` mode; `on_motion` / `on_object` had no pre-roll and used hardcoded
post-roll constants. These tests pin the post-roll wiring (the pre-roll flush
lives in the frame loop and needs a live capture, so it is covered by the loop's
structure rather than a unit test).
"""

import os
import time
import uuid
from datetime import datetime, timedelta, timezone

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


# ── On-disk pre-roll: staging paths + retention trim ──


def test_preroll_paths_live_under_camera_preroll_dir():
    w = _worker("on_motion")
    d = w._preroll_dir()
    assert d.endswith(os.path.join(str(w.camera_id), ".preroll"))
    p = w._preroll_temp_path(datetime(2026, 7, 29, 1, 2, 3, tzinfo=timezone.utc))
    assert p.startswith(d) and p.endswith(".mp4")


def test_preroll_trim_keeps_minimal_suffix_covering_clip_pre():
    # clip_pre=5s. Segments starting 12s, 6s, and 1s ago. The 12s-old one is
    # redundant (the 6s-old one alone already reaches back >= 5s), so only it
    # is dropped; the 6s + 1s segments are kept.
    w = _worker("on_motion", clip_pre=5)
    now = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)
    w._preroll_done = [
        ("/nope/a.mp4", now - timedelta(seconds=12), now - timedelta(seconds=7)),
        ("/nope/b.mp4", now - timedelta(seconds=6), now - timedelta(seconds=1)),
        ("/nope/c.mp4", now - timedelta(seconds=1), now),
    ]
    w._preroll_trim(now)
    starts = [round((now - s).total_seconds()) for _p, s, _e in w._preroll_done]
    assert starts == [6, 1]  # 12s-old segment dropped


def test_preroll_trim_keeps_all_when_coverage_is_short():
    # Two recent segments that together only span 3s (< clip_pre): keep both.
    w = _worker("on_motion", clip_pre=5)
    now = datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc)
    w._preroll_done = [
        ("/nope/a.mp4", now - timedelta(seconds=3), now - timedelta(seconds=1)),
        ("/nope/b.mp4", now - timedelta(seconds=1), now),
    ]
    w._preroll_trim(now)
    assert len(w._preroll_done) == 2


def test_preroll_state_initialized():
    w = _worker("on_motion")
    assert w._preroll_writer is None
    assert w._preroll_done == []
