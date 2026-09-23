"""Camera content-health detection: frozen / obscured / tampered views (#212).

``camera_offline`` only catches dead connections. The dangerous real-world
failures keep a normal-looking stream alive while coverage is silently gone:

* **Frozen decoder** - the RTSP session stays up but frames stop changing.
  A live frame is never byte-identical to the last one (sensor noise, codec
  dither), so a run of *identical* perceptual hashes over several minutes is
  an unambiguous freeze, distinct from a merely quiet scene (whose frames
  still differ slightly).
* **Obscured / tampered view** - a covered lens, a camera turned to a wall,
  or a defocused dome produces a near-uniform, low-variance frame. Sustained
  very low spatial variance flags that the scene we think we see is gone.

This module is the pure detection core: it takes cheap per-frame features
(a perceptual hash and a variance number, computed by the caller from an
already-decoded frame) and decides when to raise ``degraded`` or
``recovered``. No OpenCV import here, so it is trivially unit-testable and
carries no decode cost of its own.

Distinguishing frozen (defect) from quiet (normal) is explicit: freeze needs
*exact* hash stability; a quiet scene keeps changing hashes and never trips.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re

# Defaults. Tunable per deployment; the caller passes overrides.
FREEZE_SECONDS = 180.0          # identical frames this long => frozen
OBSCURE_VARIANCE = 8.0          # grayscale variance below this => obscured
OBSCURE_SECONDS = 180.0         # sustained this long => obscured
RECOVER_SECONDS = 10.0          # healthy again this long => recovered
SCENE_CHANGE_DISTANCE = 24      # average-hash Hamming distance
SCENE_CHANGE_SECONDS = 180.0    # persistent change this long => degraded
VLM_MISMATCH_SECONDS = 180.0
VLM_MIN_CONFIDENCE = 0.75


@dataclass
class _State:
    # Freeze tracking.
    last_hash: int | None = None
    frozen_since: float | None = None
    # Obscuration tracking.
    low_var_since: float | None = None
    reference_hash: int | None = None
    scene_changed_since: float | None = None
    vlm_mismatch_since: float | None = None
    # Current degraded verdict + when health returned.
    degraded: bool = False
    degraded_reason: str | None = None
    healthy_since: float | None = None


class ContentHealthDetector:
    """Per-camera frozen/obscured detector over a stream of frame features.

    Feed :meth:`update` cheap features sampled on an interval (e.g. once a
    second): the perceptual hash of a downsampled grayscale frame and that
    frame's variance. It returns a transition string when the verdict
    changes, else ``None``:

    * ``"degraded"`` - first time a freeze or obscuration is confirmed.
    * ``"recovered"`` - health has returned for ``recover_seconds``.

    The transition carries a reason via :attr:`reason`.
    """

    def __init__(
        self,
        *,
        freeze_seconds: float = FREEZE_SECONDS,
        obscure_variance: float = OBSCURE_VARIANCE,
        obscure_seconds: float = OBSCURE_SECONDS,
        recover_seconds: float = RECOVER_SECONDS,
        scene_change_distance: int = SCENE_CHANGE_DISTANCE,
        scene_change_seconds: float = SCENE_CHANGE_SECONDS,
        detect_freeze: bool = True,
        detect_obscure: bool = True,
        detect_scene_change: bool = False,
        vlm_mismatch_seconds: float = VLM_MISMATCH_SECONDS,
        vlm_min_confidence: float = VLM_MIN_CONFIDENCE,
    ) -> None:
        self.freeze_seconds = freeze_seconds
        self.obscure_variance = obscure_variance
        self.obscure_seconds = obscure_seconds
        self.recover_seconds = recover_seconds
        self.scene_change_distance = scene_change_distance
        self.scene_change_seconds = scene_change_seconds
        self.detect_freeze = detect_freeze
        self.detect_obscure = detect_obscure
        self.detect_scene_change = detect_scene_change
        self.vlm_mismatch_seconds = vlm_mismatch_seconds
        self.vlm_min_confidence = vlm_min_confidence
        self._s = _State()
        self.reason: str | None = None

    def update(self, frame_hash: int, variance: float, now: float) -> str | None:
        """Fold in one frame's features at monotonic time ``now``.

        Returns ``"degraded"``, ``"recovered"``, or ``None``.
        """
        s = self._s

        frozen = self._track_freeze(frame_hash, now) if self.detect_freeze else False
        obscured = self._track_obscure(variance, now) if self.detect_obscure else False
        scene_changed = (
            self._track_scene_change(frame_hash, now)
            if self.detect_scene_change else False
        )

        unhealthy = frozen or obscured or scene_changed
        reason = (
            "frozen" if frozen else
            "obscured" if obscured else
            "scene_changed" if scene_changed else None
        )

        if unhealthy:
            s.healthy_since = None
            if not s.degraded:
                s.degraded = True
                s.degraded_reason = reason
                self.reason = reason
                return "degraded"
            return None

        # Healthy this frame. Require a sustained clear stretch before we
        # declare recovery, so a single good frame does not flap the state.
        if s.degraded:
            if s.healthy_since is None:
                s.healthy_since = now
            elif now - s.healthy_since >= self.recover_seconds:
                s.degraded = False
                s.degraded_reason = None
                s.healthy_since = None
                self.reason = "recovered"
                return "recovered"
        return None

    def update_vlm(self, expected_scene: bool, confidence: float, now: float) -> str | None:
        """Fold in a low-frequency VLM scene-baseline result.

        A single model response never changes health. Only a confident,
        sustained mismatch does, and an expected result clears the pending
        mismatch so ordinary activity cannot flap the camera state.
        """
        s = self._s
        if expected_scene or confidence < self.vlm_min_confidence:
            s.vlm_mismatch_since = None
            return None
        if s.vlm_mismatch_since is None:
            s.vlm_mismatch_since = now
            return None
        if now - s.vlm_mismatch_since < self.vlm_mismatch_seconds:
            return None
        if not s.degraded:
            s.degraded = True
            s.degraded_reason = "scene_mismatch"
            self.reason = "scene_mismatch"
            s.healthy_since = None
            return "degraded"
        return None

    def _track_freeze(self, frame_hash: int, now: float) -> bool:
        s = self._s
        if s.last_hash is not None and frame_hash == s.last_hash:
            if s.frozen_since is None:
                s.frozen_since = now
            elif now - s.frozen_since >= self.freeze_seconds:
                return True
        else:
            s.frozen_since = None
        s.last_hash = frame_hash
        return False

    def _track_obscure(self, variance: float, now: float) -> bool:
        s = self._s
        if variance < self.obscure_variance:
            if s.low_var_since is None:
                s.low_var_since = now
            elif now - s.low_var_since >= self.obscure_seconds:
                return True
        else:
            s.low_var_since = None
        return False

    def _track_scene_change(self, frame_hash: int, now: float) -> bool:
        """Detect a persistent re-aim/tamper against the startup reference.

        This path is opt-in because a camera's normal composition can change
        seasonally or after a deliberate reposition. It is intentionally
        separate from freeze and obscuration, and a confirmed change remains
        degraded until the worker is restarted or the detector is reset.
        """
        s = self._s
        if s.reference_hash is None:
            s.reference_hash = frame_hash
            return False
        distance = (s.reference_hash ^ frame_hash).bit_count()
        if distance >= self.scene_change_distance:
            if s.scene_changed_since is None:
                s.scene_changed_since = now
            return now - s.scene_changed_since >= self.scene_change_seconds
        s.scene_changed_since = None
        return False

    @property
    def is_degraded(self) -> bool:
        return self._s.degraded


def parse_scene_health_response(text: str | None) -> tuple[bool, float, str] | None:
    """Parse the constrained VLM response used by the scene check.

    Accepts JSON directly or a JSON object embedded in a short response. A
    malformed answer is ignored rather than becoming a degraded verdict.
    """
    if not text:
        return None
    candidate = text.strip()
    match = re.search(r"\{.*\}", candidate, re.DOTALL)
    if match:
        candidate = match.group(0)
    try:
        data = json.loads(candidate)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("expected_scene"), bool):
        return None
    try:
        confidence = float(data.get("confidence"))
    except (TypeError, ValueError):
        return None
    if not 0.0 <= confidence <= 1.0:
        return None
    return data["expected_scene"], confidence, str(data.get("reason") or "")[:240]
