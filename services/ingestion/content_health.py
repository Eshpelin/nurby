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

# Defaults. Tunable per deployment; the caller passes overrides.
FREEZE_SECONDS = 180.0          # identical frames this long => frozen
OBSCURE_VARIANCE = 8.0          # grayscale variance below this => obscured
OBSCURE_SECONDS = 180.0         # sustained this long => obscured
RECOVER_SECONDS = 10.0          # healthy again this long => recovered


@dataclass
class _State:
    # Freeze tracking.
    last_hash: int | None = None
    frozen_since: float | None = None
    # Obscuration tracking.
    low_var_since: float | None = None
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
        detect_freeze: bool = True,
        detect_obscure: bool = True,
    ) -> None:
        self.freeze_seconds = freeze_seconds
        self.obscure_variance = obscure_variance
        self.obscure_seconds = obscure_seconds
        self.recover_seconds = recover_seconds
        self.detect_freeze = detect_freeze
        self.detect_obscure = detect_obscure
        self._s = _State()
        self.reason: str | None = None

    def update(self, frame_hash: int, variance: float, now: float) -> str | None:
        """Fold in one frame's features at monotonic time ``now``.

        Returns ``"degraded"``, ``"recovered"``, or ``None``.
        """
        s = self._s

        frozen = self._track_freeze(frame_hash, now) if self.detect_freeze else False
        obscured = self._track_obscure(variance, now) if self.detect_obscure else False

        unhealthy = frozen or obscured
        reason = "frozen" if frozen else ("obscured" if obscured else None)

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

    @property
    def is_degraded(self) -> bool:
        return self._s.degraded
