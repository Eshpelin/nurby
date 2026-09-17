"""Schema-constrained VLM caption fields and real observation confidence.

Issue #221. Two related honesty fixes for the values rules key off.

1. Observation confidence. The live VLM caption path used to stamp a hardcoded
   ``0.8`` onto every captioned observation (``vlm_queue._patch_observation``).
   Nothing measured that number, so any consumer that trusted observation
   confidence (rule ``min_confidence``, #196 tuning suggestions, absence/pattern
   scoring, search ranking) ranked on fiction. Caption providers do not expose a
   calibrated caption confidence uniformly (Anthropic returns none for vision,
   OpenAI only partially), so we do NOT invent one. Instead the observation
   carries the strongest object detection's own confidence, which is a real,
   measured detector score. When the scene is motion-only with no detections,
   confidence stays ``None`` rather than a fabricated value.

   Semantics, stated once so every consumer can be explicit:

       ``Observation.confidence`` is the detector confidence of the strongest
       object detection in the keyframe, in [0, 1], or ``None`` when the frame
       carried no scored detection. It is NOT a VLM/caption confidence.

2. Schema-constrained caption fields. Any caption field a machine acts on is
   validated against a schema with defined parse-failure behavior, extending the
   structured-output pattern already used by action classification
   (:data:`services.perception.actions.ACTION_SCHEMA`) and the analyzer verify
   path. :func:`validate_against_schema` is a tiny, dependency-free validator for
   the subset of JSON Schema those contracts use (object shape, required keys,
   enum membership, numeric bounds, ``additionalProperties`` stripping). The
   defined failure behavior is: a value that cannot be coerced to a valid one is
   dropped (set to ``None`` / removed), never guessed.

The helpers are pure and side-effect free so the contract is unit-testable
without a VLM, a provider, or a database.
"""

from __future__ import annotations

import math
from typing import Any

# ── Real observation confidence ───────────────────────────────────────────────


def validate_confidence(value: Any) -> float | None:
    """Coerce a raw confidence into a real value in [0, 1], or ``None``.

    Defined parse-failure behavior: anything that is not a finite number in a
    sensible range is rejected to ``None`` rather than clamped-from-garbage or
    replaced with a placeholder. A finite number outside [0, 1] is clamped,
    since detectors occasionally emit e.g. 1.0000001 from rounding.
    """
    try:
        c = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(c):
        return None
    return max(0.0, min(1.0, c))


def detection_confidence(detections: list[dict] | None) -> float | None:
    """Strongest object detection's real confidence, or ``None``.

    This is the sole source of :attr:`Observation.confidence` on the VLM caption
    path. It reflects the detector's own measured score for the most confident
    object in frame. Returns ``None`` for a motion-only frame with no scored
    detection, so consumers can tell "no signal" apart from "low confidence"
    instead of reading a fabricated constant.
    """
    if not detections:
        return None
    best: float | None = None
    for det in detections:
        if not isinstance(det, dict):
            continue
        c = validate_confidence(det.get("confidence"))
        if c is None:
            continue
        if best is None or c > best:
            best = c
    return best


# ── Schema-constrained caption fields ─────────────────────────────────────────

# Structured caption attributes a machine may act on. Free-text prose stays on
# ``Observation.vlm_description``; this is the validated, queryable surface that
# rules and search consume as it grows. Additive and fully optional today: an
# absent field means "not asserted", never a guess. Extend field by field as
# each becomes machine-consumed (issue #221 scope: gradual, not wholesale).
CAPTION_ATTRIBUTE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        # Coarse machine-readable scene state, when the model asserts one.
        "state": {"type": "string", "enum": ["active", "idle", "empty", "unknown"]},
        # Non-negative person count read from the frame.
        "person_count": {"type": "integer", "minimum": 0, "maximum": 100},
        # The caption model's own confidence in the structured read, when a
        # provider exposes one. Distinct from the detector-derived
        # Observation.confidence above; kept per-pass, never fabricated.
        "caption_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": [],
    "additionalProperties": False,
}


def validate_against_schema(data: Any, schema: dict) -> tuple[bool, dict]:
    """Validate ``data`` against a minimal JSON-Schema subset.

    Supports the subset the VLM structured-output contracts use: ``type:
    object`` with ``properties`` whose members are ``string`` (optional
    ``enum``), ``integer``/``number`` (optional ``minimum``/``maximum``),
    ``boolean``; a ``required`` list; and ``additionalProperties: false``.

    Returns ``(ok, cleaned)``. ``cleaned`` keeps only known, coercible,
    in-range fields; unknown keys are dropped when ``additionalProperties`` is
    false. ``ok`` is ``False`` when a required field is missing or a present
    field fails to coerce, but ``cleaned`` is always safe to persist. This is
    the defined parse-failure behavior: drop the bad field, never invent one.
    """
    if not isinstance(data, dict):
        return False, {}

    props: dict = schema.get("properties", {}) or {}
    required: list = schema.get("required", []) or []
    allow_extra = schema.get("additionalProperties", True) is not False

    cleaned: dict = {}
    ok = True

    for key, spec in props.items():
        if key not in data:
            continue
        coerced = _coerce_field(data[key], spec)
        if coerced is _INVALID:
            ok = False
            continue
        cleaned[key] = coerced

    if allow_extra:
        for key, value in data.items():
            if key not in props:
                cleaned[key] = value

    for key in required:
        if key not in cleaned:
            ok = False

    return ok, cleaned


class _Invalid:
    __slots__ = ()


_INVALID = _Invalid()


def _coerce_field(value: Any, spec: dict) -> Any:
    t = spec.get("type")
    if t == "string":
        s = value if isinstance(value, str) else None
        if s is None:
            return _INVALID
        enum = spec.get("enum")
        if enum is not None and s not in enum:
            return _INVALID
        return s
    if t == "integer":
        try:
            n = int(value)
        except (TypeError, ValueError):
            return _INVALID
        if isinstance(value, bool):  # bool is an int subclass; reject it
            return _INVALID
        return _bounded(n, spec)
    if t == "number":
        try:
            n = float(value)
        except (TypeError, ValueError):
            return _INVALID
        if not math.isfinite(n):
            return _INVALID
        return _bounded(n, spec)
    if t == "boolean":
        return value if isinstance(value, bool) else _INVALID
    # Unconstrained type: pass through.
    return value


def _bounded(n, spec: dict):
    lo = spec.get("minimum")
    hi = spec.get("maximum")
    if lo is not None and n < lo:
        return _INVALID
    if hi is not None and n > hi:
        return _INVALID
    return n


def validate_caption_attributes(data: Any) -> dict:
    """Validate raw caption attributes, returning only the safe, in-schema fields.

    Convenience wrapper over :func:`validate_against_schema` for
    :data:`CAPTION_ATTRIBUTE_SCHEMA`. Parse failure on any single field drops
    that field; the rest still persist. Never raises.
    """
    _ok, cleaned = validate_against_schema(data, CAPTION_ATTRIBUTE_SCHEMA)
    return cleaned
