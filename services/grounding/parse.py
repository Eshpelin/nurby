"""Parse and rescale LocateAnything coordinate output.

The model is an autoregressive text decoder. It emits structured text with
coordinate tokens, ``<box> x1, y1, x2, y2 </box>`` for boxes and
``<box> x, y </box>`` for points, with coordinates as **normalized integers
in [0, 1000]**. There is no softmax and therefore **no calibrated
confidence** (design §1.1/§6): we never invent a score.

This module is pure (no GPU, no network) so every adversarial output shape
is unit-testable in CI (design §10). It must survive (design §6):

- boxes out of order (x2 < x1), values < 0 or > 1000 (clamp),
- zero-area boxes (dropped, points kept),
- duplicate / multiple boxes,
- a truncated trailing ``<box>`` when the model hits the token cap,
- empty output (= "not found"),
- prose mixed with boxes (ignored).

Rescale uses the dimensions of the image that was *sent to the model*. Because
the coordinates are normalized to [0, 1000], rescaling to those dimensions is
resolution-independent and correct regardless of any server-side resize.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("nurby.grounding.parse")

# Non-greedy capture of everything between a <box> open and its close. The
# close is optional at end-of-string so a truncated final token is captured
# and then rejected by the number-count check below rather than silently
# swallowing the rest of the output.
_BOX_RE = re.compile(r"<box>(.*?)(?:</box>|$)", re.IGNORECASE | re.DOTALL)
# Signed integers or decimals. The model emits ints, but tolerate decimals.
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")

_COORD_MAX = 1000.0


@dataclass(frozen=True)
class GroundedBox:
    """One located thing.

    ``bbox_norm`` is ``(x1, y1, x2, y2)`` in [0, 1] (resolution-independent,
    what the API hands the frontend). ``bbox_px`` is the same in pixels of the
    sent image. ``confidence`` is **always None** in V1, by design: the model
    has no calibrated score and we refuse to surface a fake one.
    """

    bbox_norm: tuple[float, float, float, float]
    bbox_px: tuple[int, int, int, int]
    label: str
    is_point: bool = False
    confidence: None = None


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def parse_grounding_output(
    raw: str,
    width: int,
    height: int,
    *,
    label: str,
    max_boxes: int,
) -> list[GroundedBox]:
    """Parse ``<box>`` tokens from ``raw`` into rescaled boxes.

    ``label`` is attached to every box. In V1 the user's prompt *is* the
    label (we do not try to parse free-form semantic labels out of the prose,
    which is fragile); this keeps the result honest and stable. ``max_boxes``
    hard-caps how many boxes we return so a crafted prompt cannot flood the
    parser or downstream rule actions (design §9).
    """
    if not raw or width <= 0 or height <= 0:
        return []

    out: list[GroundedBox] = []
    dropped = 0
    for match in _BOX_RE.finditer(raw):
        nums = [float(n) for n in _NUM_RE.findall(match.group(1))]

        if len(nums) >= 4:
            x1, y1, x2, y2 = (_clamp(n, 0.0, _COORD_MAX) for n in nums[:4])
            # Reorder so the box is well-formed regardless of emission order.
            if x2 < x1:
                x1, x2 = x2, x1
            if y2 < y1:
                y1, y2 = y2, y1
            # Zero-area boxes carry no localization; drop them.
            if x2 <= x1 or y2 <= y1:
                dropped += 1
                continue
            out.append(_make_box(x1, y1, x2, y2, width, height, label, is_point=False))
        elif len(nums) == 2:
            # A point. Represent it as a degenerate box at (x, y) and flag it
            # so the UI can render a marker instead of a rectangle.
            x, y = (_clamp(n, 0.0, _COORD_MAX) for n in nums[:2])
            out.append(_make_box(x, y, x, y, width, height, label, is_point=True))
        else:
            # Truncated / malformed token (e.g. output hit the cap mid-box).
            dropped += 1
            continue

        if len(out) >= max_boxes:
            break

    if dropped:
        logger.debug("grounding parse dropped %d malformed/zero-area boxes", dropped)
    return out


def _make_box(
    x1: float, y1: float, x2: float, y2: float,
    width: int, height: int, label: str, *, is_point: bool,
) -> GroundedBox:
    nx1, ny1, nx2, ny2 = x1 / _COORD_MAX, y1 / _COORD_MAX, x2 / _COORD_MAX, y2 / _COORD_MAX
    return GroundedBox(
        bbox_norm=(nx1, ny1, nx2, ny2),
        bbox_px=(
            round(nx1 * width), round(ny1 * height),
            round(nx2 * width), round(ny2 * height),
        ),
        label=label,
        is_point=is_point,
    )
