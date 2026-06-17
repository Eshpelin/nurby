"""On-demand annotated-recording rendering + cache.

Non-destructive: the stored recording is never modified. When a user asks to
download a recording "with annotations", we render an annotated copy on first
request and cache it (keyed by source path + mtime + size + options), mirroring
services/guardian/video.py blur_clip. Subsequent identical requests serve the
cache.

Three optional overlays, driven by the camera's observations:
- boxes: detection rectangles + label for detections >= min_confidence
- captions: the VLM description, timed to each observation's window
- strip: a colour-coded bar along the very bottom (human / pet / vehicle lanes)
  spanning the clip, with a moving playhead, so fast-scrubbing in any player
  shows when each class appeared.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import textwrap

from shared.config import settings
from shared.ffmpeg_safe import (
    PROTOCOL_WHITELIST_ARGS,
    DisallowedFfmpegArgError,
    assert_allowed_args,
)
from shared.paths import safe_getsize

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(settings.recordings_path, "annotated")

# Label -> priority lane. The top three things people scrub for.
_HUMAN = {"person"}
_PET = {"cat", "dog", "bird", "rabbit", "horse", "sheep", "cow"}
_VEHICLE = {"car", "truck", "bus", "motorcycle", "motorbike", "bicycle", "train", "boat"}
LANES = ("human", "pet", "vehicle")
# OpenCV is BGR.
LANE_BGR = {"human": (246, 130, 59), "pet": (70, 200, 70), "vehicle": (15, 185, 250)}
LANE_LABEL = {"human": "Human", "pet": "Pet", "vehicle": "Vehicle"}


def classify_lane(label: str | None) -> str | None:
    """Map a detection label to a priority lane, or None if not prioritised."""
    if not label:
        return None
    lab = label.strip().lower()
    if lab in _HUMAN:
        return "human"
    if lab in _PET:
        return "pet"
    if lab in _VEHICLE:
        return "vehicle"
    return None


def lanes_in(detections: list[dict], min_conf: float) -> set[str]:
    """Set of priority lanes present among detections meeting the threshold."""
    out: set[str] = set()
    for d in detections or []:
        if float(d.get("confidence") or 0.0) < min_conf:
            continue
        lane = classify_lane(d.get("label"))
        if lane:
            out.add(lane)
    return out


def _coalesce(intervals: list[tuple[float, float]], gap: float = 0.6) -> list[tuple[float, float]]:
    """Merge sorted [start,end) intervals that touch or sit within `gap`."""
    merged: list[tuple[float, float]] = []
    for s, e in sorted(intervals):
        if merged and s <= merged[-1][1] + gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def build_object_segments(samples: list[tuple[float, set]], duration: float) -> list[dict]:
    """Turn per-observation lane samples into coalesced per-lane segments.

    `samples` is a list of (offset_seconds, lanes_present) sorted by offset.
    Each sample's lanes hold until the next sample (or end of clip). Returns
    ``[{lane, start, end}]``."""
    if not samples:
        return []
    raw: dict[str, list[tuple[float, float]]] = {lane: [] for lane in LANES}
    for i, (off, lanes) in enumerate(samples):
        nxt = samples[i + 1][0] if i + 1 < len(samples) else duration
        start = max(0.0, off)
        end = min(duration, nxt) if duration else nxt
        if end <= start:
            end = start + 1.0
        for lane in lanes:
            if lane in raw:
                raw[lane].append((start, end))
    out: list[dict] = []
    for lane in LANES:
        for s, e in _coalesce(raw[lane]):
            out.append({"lane": lane, "start": round(s, 2), "end": round(e, 2)})
    return out


def _cache_key(src_path: str, opts: dict) -> str:
    norm = json.dumps(opts, sort_keys=True, default=str)
    try:
        st = os.stat(src_path)
        sig = f"{os.path.abspath(src_path)}|{st.st_mtime_ns}|{st.st_size}|{norm}"
    except OSError:
        sig = f"{os.path.abspath(src_path)}|{norm}"
    return hashlib.sha256(sig.encode()).hexdigest()[:24]


def _scale_bbox(bbox, sx: float, sy: float) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    return int(x1 * sx), int(y1 * sy), int(x2 * sx), int(y2 * sy)


def _draw_strip(frame, segments: list[dict], t: float, duration: float, w: int, h: int) -> None:
    import cv2
    if duration <= 0:
        return
    lane_h = max(4, h // 90)
    base = h - lane_h * len(LANES) - 2
    # dim backdrop so lanes read on any footage
    cv2.rectangle(frame, (0, base - 2), (w, h), (0, 0, 0), -1)
    for li, lane in enumerate(LANES):
        y0 = base + li * lane_h
        for seg in segments:
            if seg["lane"] != lane:
                continue
            x0 = int((seg["start"] / duration) * w)
            x1 = int((seg["end"] / duration) * w)
            cv2.rectangle(frame, (x0, y0), (max(x0 + 1, x1), y0 + lane_h - 1), LANE_BGR[lane], -1)
    # playhead
    px = int((min(t, duration) / duration) * w)
    cv2.line(frame, (px, base - 2), (px, h), (255, 255, 255), 1)


def _draw_caption(frame, text: str, w: int, h: int) -> None:
    import cv2
    wrapped = textwrap.wrap(text, width=max(20, w // 12))[:3]
    if not wrapped:
        return
    fh = 18
    box_h = fh * len(wrapped) + 8
    y0 = h - box_h - 24
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, y0), (w, y0 + box_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)
    for i, line in enumerate(wrapped):
        cv2.putText(frame, line, (8, y0 + fh * (i + 1)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (255, 255, 255), 1, cv2.LINE_AA)


def render_annotated(
    src_path: str,
    observations: list[dict],
    opts: dict,
    cam_w: int | None = None,
    cam_h: int | None = None,
) -> str:
    """Render (or return cached) annotated copy of ``src_path``. Sync; dispatch
    to a thread from async callers. ``observations`` is a list of
    ``{offset: float_seconds, object_detections: {...}, vlm_description: str}``
    (offset relative to the recording start, precomputed by the caller)."""
    import cv2

    os.makedirs(CACHE_DIR, exist_ok=True)
    dest = os.path.join(CACHE_DIR, f"{_cache_key(src_path, opts)}.mp4")
    if safe_getsize(dest) > 0:
        return dest

    cap = cv2.VideoCapture(src_path)
    if not cap.isOpened():
        raise RuntimeError("cannot open source recording")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    duration = (total / fps) if total else 0.0
    min_conf = float(opts.get("min_conf", 0.8))
    sx = (w / cam_w) if cam_w else 1.0
    sy = (h / cam_h) if cam_h else 1.0

    obs_sorted = sorted(observations, key=lambda o: o.get("offset", 0.0))
    windows: list[tuple[int, int, list, str | None]] = []
    samples: list[tuple[float, set]] = []
    for i, o in enumerate(obs_sorted):
        off = float(o.get("offset", 0.0))
        nxt = float(obs_sorted[i + 1].get("offset", duration)) if i + 1 < len(obs_sorted) else duration
        start_f = max(0, int(round(off * fps)))
        end_f = max(start_f + 1, int(round((nxt if nxt > off else off + 2.0) * fps)))
        dets = (o.get("object_detections") or {}).get("objects") or []
        windows.append((start_f, end_f, dets, o.get("vlm_description")))
        samples.append((off, lanes_in(dets, min_conf)))
    segments = build_object_segments(samples, duration) if opts.get("strip") else []

    tmp = dest + ".tmp.mp4"
    writer = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError("cannot open video writer")

    idx = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            t = idx / fps
            if opts.get("boxes"):
                for sf, ef, dets, _ in windows:
                    if sf <= idx < ef:
                        for d in dets:
                            if float(d.get("confidence") or 0.0) < min_conf:
                                continue
                            bbox = d.get("bbox")
                            if not bbox or len(bbox) != 4:
                                continue
                            lane = classify_lane(d.get("label"))
                            color = LANE_BGR.get(lane or "", (200, 200, 200))
                            x1, y1, x2, y2 = _scale_bbox(bbox, sx, sy)
                            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                            label = str(d.get("label") or "")
                            if label:
                                cv2.putText(frame, label, (x1, max(12, y1 - 4)),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
            if opts.get("captions"):
                for sf, ef, _, vlm in windows:
                    if sf <= idx < ef and vlm:
                        _draw_caption(frame, vlm, w, h)
                        break
            if opts.get("strip") and segments:
                _draw_strip(frame, segments, t, duration, w, h)
            writer.write(frame)
            idx += 1
    finally:
        cap.release()
        writer.release()

    # Transcode to broadly-playable H.264 (faststart) and mux original audio if
    # present. If ffmpeg is unavailable/fails, keep the mp4v render as-is.
    cmd = [
        "ffmpeg", *PROTOCOL_WHITELIST_ARGS, "-y", "-loglevel", "error",
        "-i", tmp, "-i", src_path,
        "-map", "0:v:0", "-map", "1:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-movflags", "+faststart", "-shortest",
        dest,
    ]
    try:
        assert_allowed_args(cmd)
        proc = subprocess.run(cmd, capture_output=True, timeout=600)
        if proc.returncode == 0 and safe_getsize(dest) > 0:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return dest
        logger.warning("annotate ffmpeg transcode failed rc=%s; keeping mp4v", proc.returncode)
    except DisallowedFfmpegArgError as exc:
        logger.error("refusing annotate ffmpeg invocation: %s; keeping mp4v", exc)
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("annotate ffmpeg unavailable (%s); keeping mp4v", exc)

    os.replace(tmp, dest)
    return dest
