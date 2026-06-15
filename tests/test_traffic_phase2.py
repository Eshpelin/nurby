"""Traffic Phase 2: speed_over (two-line gate timing) and red_light_cross
(tripwire gated by a red-light time window)."""

import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from services.api.routes.rules import _straddle_boxes, _window_midpoint
from tests._engine_helpers import FakeRule, install_engine

# A horizontal gate at y=100 and another at y=300 (200px apart).
GATE_A = [[0, 100], [400, 100]]
GATE_B = [[0, 300], [400, 300]]


def _frame(cam, ts, prev_box, cur_box, label="car"):
    return {
        "camera_id": cam,
        "timestamp": ts.isoformat(),
        "tracks": [{"track_id": 1, "label": label, "bbox": cur_box,
                    "prev_bbox": prev_box, "state": "moving"}],
    }


# ── speed_over ─────────────────────────────────────────────────────

def _speed_run(monkeypatch, pattern, dt_seconds):
    rule = FakeRule(name="r", trigger_pattern=pattern)
    eng, rec = install_engine(monkeypatch, [rule])
    t0 = datetime(2026, 6, 13, 12, 0, 0, tzinfo=timezone.utc)
    a_prev, a_cur = _straddle_boxes(GATE_A[0], GATE_A[1])
    b_prev, b_cur = _straddle_boxes(GATE_B[0], GATE_B[1])
    asyncio.run(eng.evaluate(_frame("cam-1", t0, a_prev, a_cur)))
    asyncio.run(eng.evaluate(_frame("cam-1", t0 + timedelta(seconds=dt_seconds), b_prev, b_cur)))
    return rec.call_count


def test_speed_over_fires_above_threshold(monkeypatch):
    # 10 m in 0.5 s = 20 m/s = 72 km/h, over a 30 km/h limit.
    p = {"type": "speed_over", "line_a": GATE_A, "line_b": GATE_B,
         "distance_m": 10, "min_speed_kmh": 30, "label": "car"}
    assert _speed_run(monkeypatch, p, 0.5) == 1


def test_speed_over_silent_below_threshold(monkeypatch):
    # 10 m in 3 s = 3.33 m/s = 12 km/h, under a 30 km/h limit.
    p = {"type": "speed_over", "line_a": GATE_A, "line_b": GATE_B,
         "distance_m": 10, "min_speed_kmh": 30, "label": "car"}
    assert _speed_run(monkeypatch, p, 3.0) == 0


def test_speed_over_needs_both_gates(monkeypatch):
    # Only crossing gate A (never B) does not measure.
    p = {"type": "speed_over", "line_a": GATE_A, "line_b": GATE_B,
         "distance_m": 10, "min_speed_kmh": 30}
    rule = FakeRule(name="r", trigger_pattern=p)
    eng, rec = install_engine(monkeypatch, [rule])
    t0 = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)
    a_prev, a_cur = _straddle_boxes(GATE_A[0], GATE_A[1])
    asyncio.run(eng.evaluate(_frame("cam-1", t0, a_prev, a_cur)))
    assert rec.call_count == 0


def test_speed_over_label_filter(monkeypatch):
    p = {"type": "speed_over", "line_a": GATE_A, "line_b": GATE_B,
         "distance_m": 10, "min_speed_kmh": 30, "label": "car"}
    rule = FakeRule(name="r", trigger_pattern=p)
    eng, rec = install_engine(monkeypatch, [rule])
    t0 = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)
    a_prev, a_cur = _straddle_boxes(GATE_A[0], GATE_A[1])
    b_prev, b_cur = _straddle_boxes(GATE_B[0], GATE_B[1])
    asyncio.run(eng.evaluate(_frame("cam-1", t0, a_prev, a_cur, label="person")))
    asyncio.run(eng.evaluate(_frame("cam-1", t0 + timedelta(seconds=0.5), b_prev, b_cur, label="person")))
    assert rec.call_count == 0


# ── red_light_cross ────────────────────────────────────────────────

LA = ZoneInfo("America/Los_Angeles")
LINE = [[0, 200], [400, 200]]


def _redlight_run(monkeypatch, pattern, hhmm_local):
    rule = FakeRule(name="r", trigger_pattern=pattern)
    eng, rec = install_engine(monkeypatch, [rule])
    h, m = hhmm_local
    local = datetime(2026, 6, 13, h, m, tzinfo=LA)
    prev_box, cur_box = _straddle_boxes(LINE[0], LINE[1])
    frame = _frame("cam-1", local.astimezone(timezone.utc), prev_box, cur_box)
    # evaluate() resolves tz from settings (UTC in tests), so exercise the
    # window check directly with the LA tz the engine would pass through.
    return eng._match_trigger(pattern, frame, rule.id, LA)


def test_red_light_fires_during_red_window(monkeypatch):
    p = {"type": "red_light_cross", "points": LINE,
         "red_after": "08:00", "red_before": "20:00", "label": "car"}
    assert _redlight_run(monkeypatch, p, (12, 0)) is True


def test_red_light_silent_outside_window(monkeypatch):
    p = {"type": "red_light_cross", "points": LINE,
         "red_after": "08:00", "red_before": "20:00", "label": "car"}
    assert _redlight_run(monkeypatch, p, (23, 0)) is False


def test_red_light_overnight_window(monkeypatch):
    # 22:00 -> 06:00 wraps midnight; 02:00 is inside.
    p = {"type": "red_light_cross", "points": LINE,
         "red_after": "22:00", "red_before": "06:00", "label": "car"}
    assert _redlight_run(monkeypatch, p, (2, 0)) is True
    assert _redlight_run(monkeypatch, p, (12, 0)) is False


def test_red_light_no_window_always_red(monkeypatch):
    p = {"type": "red_light_cross", "points": LINE, "label": "car"}
    assert _redlight_run(monkeypatch, p, (3, 0)) is True


# ── window midpoint helper ─────────────────────────────────────────

def test_window_midpoint():
    assert _window_midpoint("08:00", "20:00") == (14, 0)
    assert _window_midpoint("22:00", "06:00") == (2, 0)  # overnight
    assert _window_midpoint(None, None) is None
