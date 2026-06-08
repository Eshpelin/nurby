"""Fall detection for guardian eldercare alerts.

A fallen person looks very different from a standing one in a fixed camera: the
body bounding box goes from tall to wide and drops to the lower part of the
frame, and crucially it stays that way. We use that signal, gated by a DURATION
so a brief crouch, bend, or sit-down does not fire, and attribute the fall to a
recognised dependant whose face sits inside the fallen body box.

Safety note: this is a best-effort signal, not a certified fall alarm. It is
tuned to favour catching real falls over staying silent, so expect occasional
false positives. The duration gate and the optional VLM confirm reduce them; the
marketing copy must never present it as a guaranteed safety net.

State is per (person, camera): when the person first looked fallen and whether
we already alerted for this episode. The pure helpers are side-effect free so
the heuristic is unit-testable without a pipeline.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# bbox = [x0, y0, x1, y1] in frame pixels.
FALL_ASPECT_RATIO = 1.25  # width / height at or above this looks horizontal
FALL_LOWER_FRAME = 0.55  # bbox vertical centre must sit below this frame fraction
HOLD_SECONDS = 5.0  # must look fallen at least this long before alerting
CLEAR_SECONDS = 3.0  # upright at least this long clears the episode

# (person_id, camera_id) -> {"since": float|None, "alerted": bool, "cleared_since": float|None}
_state: dict[tuple[str, str], dict] = {}


def looks_fallen(
    bbox,
    frame_h: int,
    *,
    aspect: float = FALL_ASPECT_RATIO,
    lower: float = FALL_LOWER_FRAME,
) -> bool:
    """True if a person bbox looks horizontal and low in the frame."""
    if not bbox or len(bbox) != 4:
        return False
    x0, y0, x1, y1 = bbox
    w = max(0.0, x1 - x0)
    h = max(1e-6, y1 - y0)
    if w / h < aspect:
        return False
    cy = (y0 + y1) / 2.0
    return frame_h <= 0 or (cy / frame_h) >= lower


def _center(b):
    x0, y0, x1, y1 = b
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def _inside(pt, box) -> bool:
    x, y = pt
    return box[0] <= x <= box[2] and box[1] <= y <= box[3]


def person_for_fall(person_bbox, faces):
    """The recognised dependant whose face centre sits inside the fallen body
    box, or None. Returns (person_id, person_name)."""
    for f in faces or []:
        if not isinstance(f, dict):
            continue
        pid = f.get("person_id")
        name = f.get("person_name")
        fb = f.get("bbox")
        if not pid or not name or not fb or len(fb) != 4:
            continue
        if _inside(_center(fb), person_bbox):
            return str(pid), str(name)
    return None


def reset_state() -> None:
    _state.clear()


async def process(
    camera,
    person_bboxes,
    faces,
    frame_h: int,
    *,
    now: float | None = None,
    confirm=None,
) -> list[dict]:
    """Detect falls among ``person_bboxes``, attribute each to a recognised
    dependant face, and emit a guardian ``fell`` event once the fall has held
    for ``HOLD_SECONDS``. ``confirm`` is an optional async ``(camera, bbox) ->
    bool`` gate (for example a VLM check); on error it fails open and alerts.
    Returns the emitted events (for tests and telemetry)."""
    now = time.monotonic() if now is None else now
    cam_id = str(getattr(camera, "id", ""))
    emitted: list[dict] = []

    fallen_now: dict[str, tuple[str, list]] = {}
    for pb in person_bboxes or []:
        if not looks_fallen(pb, frame_h):
            continue
        hit = person_for_fall(pb, faces)
        if hit:
            fallen_now[hit[0]] = (hit[1], pb)

    seen: set[str] = set()
    for pid, (name, pb) in fallen_now.items():
        seen.add(pid)
        key = (pid, cam_id)
        st = _state.get(key) or {"since": None, "alerted": False, "cleared_since": None}
        if st["since"] is None:
            st["since"] = now
        st["cleared_since"] = None
        _state[key] = st
        if not st["alerted"] and (now - st["since"]) >= HOLD_SECONDS:
            ok = True
            if confirm is not None:
                try:
                    ok = await confirm(camera, pb)
                except Exception:  # noqa: BLE001
                    ok = True  # fail open: a confirm error must not silence a fall
            if ok:
                await _safe_emit(name, camera)
                st["alerted"] = True
                emitted.append({"kind": "fell", "person": name})

    # Clear the episode for anyone no longer fallen, after a short upright hold.
    for key, st in list(_state.items()):
        if key[1] != cam_id or key[0] in seen:
            continue
        cs = st.get("cleared_since")
        if cs is None:
            st["cleared_since"] = now
        elif (now - cs) >= CLEAR_SECONDS:
            _state.pop(key, None)
    return emitted


async def _safe_emit(person_name: str, camera) -> None:
    from services.guardian.lifecycle import notify_journey_event

    try:
        await notify_journey_event(
            "fell", "person", person_name, getattr(camera, "id", None)
        )
    except Exception:  # noqa: BLE001
        logger.debug("guardian fall emit failed", exc_info=True)
