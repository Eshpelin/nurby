"""Dependant face reveal for guardian images.

The privacy spine blurs every face. The one face a guardian is entitled to see
is their own bound dependant: when a face in the served frame matches that
person strongly enough, that single region is left sharp so the parent can see
their child while everyone else stays blurred.

Matching reuses the ``match_distance`` recorded at perception time (InsightFace
L2 on 512-dim embeddings, lower = closer; under ~1.1 is the same person). A
reveal confidence floor in [0, 1] maps to a maximum allowed distance against a
reference scale. The floor only ratchets up (see ``entitlements.reveal_threshold``)
so a stricter facility or parent setting can narrow who gets revealed but never
widen it. No qualifying match means nothing is revealed: reveal fails to blur,
never fails to expose.
"""

from __future__ import annotations

# InsightFace L2 reference. Distances below ~1.1 are the same person, so the
# reference is the upper bound of "same person": confidence 0 reveals any
# positive match, confidence 1 reveals nothing.
DEFAULT_REVEAL_REF_DISTANCE = 1.1


def confidence_to_max_distance(
    conf_floor: float, ref_distance: float = DEFAULT_REVEAL_REF_DISTANCE
) -> float:
    """Map a reveal confidence floor in [0, 1] to a maximum L2 match distance.
    Higher confidence floor -> smaller allowed distance -> stricter reveal."""
    conf = min(1.0, max(0.0, float(conf_floor)))
    return max(0.0, float(ref_distance) * (1.0 - conf))


def reveal_box_for(
    person_detections: dict | None,
    person_id,
    max_distance: float,
) -> tuple[int, int, int, int] | None:
    """The dependant's face box to leave sharp, or ``None``.

    Returns ``(x0, y0, x1, y1)`` for the face whose ``person_id`` is the bound
    dependant and whose ``match_distance`` is the smallest at or below
    ``max_distance``. ``None`` when no face clears the bar. Face ``bbox`` is in
    full-frame pixels, which is the thumbnail's own coordinate space (the
    thumbnail is the un-resized annotated frame), so no scaling is needed.
    """
    if not person_detections or not person_id:
        return None
    faces = person_detections.get("faces") if isinstance(person_detections, dict) else None
    if not isinstance(faces, list):
        return None
    pid = str(person_id)
    best: list | tuple | None = None
    best_dist: float | None = None
    for f in faces:
        if not isinstance(f, dict) or str(f.get("person_id")) != pid:
            continue
        dist = f.get("match_distance")
        bbox = f.get("bbox")
        if dist is None or not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        try:
            dist = float(dist)
        except (TypeError, ValueError):
            continue
        if dist > max_distance:
            continue
        if best_dist is None or dist < best_dist:
            best_dist, best = dist, bbox
    if best is None:
        return None
    try:
        x0, y0, x1, y1 = (int(round(float(v))) for v in best)
    except (TypeError, ValueError):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1, y1)
