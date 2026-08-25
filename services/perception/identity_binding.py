"""Bind a tracker_id to a person identity, the careful part of HAR.

Everything downstream of tracking (pose windows, the action model, VLM fusion, the
state machine) is only as good as the answer to one question: *which real person is
this track?* If a track is bound to the wrong person, every action we record for them
is wrong. So this module is deliberately small, conservative, and heavily tested.

Inputs are what the perception pipeline already has on a keyframe:
- person tracks: the YOLO person detections after `ObjectTracker.update`, each carrying a
  stable ``tracker_id`` and a ``bbox`` (and, after body re-id, an optional
  ``body_cluster_id``).
- faces: the matched faces, each carrying ``person_id`` / ``person_name`` (when the face
  matched an enrolled, consented Person) and a ``bbox``.

A track gets a ``person_id`` when a recognised face's centre sits inside that track's box
(tightest box wins under overlap). The binding is then **held for the life of the track**,
so it survives the face being occluded (e.g. while eating or turned away), which is the
v1 weakness this fixes. Identity has three honest states, never invented:
- ``person_id`` bound (a recognised, consented person),
- ``body_cluster_id`` only (a re-identified body with no confirmed Person),
- neither (an unknown, transient person).

A track can reach the first state four ways, and ``bound_by`` says which:
- ``face``: a face matched on this very frame.
- ``held``: a face matched earlier on this track, held through occlusion.
- ``body``: no face at all, but body re-identification resolved this track's appearance
  cluster to a Person it was face-confirmed against previously.
- ``handoff``: no face and no local binding, but this body cluster was bound to a Person
  recently on another camera (or before a restart). See
  :mod:`services.perception.identity_handoff`.

They are the same *state* and meaningfully different *claims*, so the rung travels with
the identity rather than being flattened away.

Guardian-facing surfaces must only show actions for the ``person_id`` state; the other two
are stored without identity or dropped, never shown to a family. Guardian's own HAR path
binds through :func:`bind_faces_to_tracks` directly, which is face-only, so a body-derived
identity never reaches it.

The module is pure and side-effect free (state is an in-memory dict keyed by camera) so the
binding contract is unit-testable without a pipeline, a tracker, or a database. The
cross-camera hand-off map is passed *into* ``update`` and the entries it may publish come
back out of :func:`writes_for`, so Redis stays on the caller's side of the boundary and
this file keeps its no-IO property. The same logic serves keyframe binding in perception
and dense-track binding in ingestion; only the source of the track boxes differs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

# A binding is dropped this many seconds after its track was last seen. Keyframes are
# sparse (seconds apart) and a person can be briefly occluded or leave and return, so this
# is generous on purpose. Tune per deployment; injectable for tests.
DEFAULT_TTL_SECONDS = 90.0


@dataclass
class Binding:
    person_id: str
    person_name: str | None
    last_seen: float
    # match_distance of the face that created/last-refreshed this binding, lower is better.
    # Lets a closer face correct an earlier weaker bind.
    match_distance: float


def _center(box) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _inside(pt, box) -> bool:
    return box[0] <= pt[0] <= box[2] and box[1] <= pt[1] <= box[3]


def _area(box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _valid_box(b) -> bool:
    return bool(b) and len(b) == 4


def bind_faces_to_tracks(person_tracks, faces) -> dict[int, dict]:
    """Pure, stateless single-frame binding. Return ``{tracker_id: {person_id,
    person_name, match_distance}}`` for the tracks a recognised face landed inside.

    A face binds to the **tightest** track box whose region contains the face centre, so
    when a small person box overlaps a large one, the face attributes to the small (closer)
    one. Faces without a ``person_id`` (unknown / unconsented) never bind. Tracks without a
    ``tracker_id`` are skipped."""
    tracks = [
        t
        for t in (person_tracks or [])
        if t.get("tracker_id") is not None and _valid_box(t.get("bbox"))
    ]
    out: dict[int, dict] = {}
    for f in faces or []:
        pid = f.get("person_id")
        fb = f.get("bbox")
        if not pid or not _valid_box(fb):
            continue
        fc = _center(fb)
        containing = [t for t in tracks if _inside(fc, t["bbox"])]
        if not containing:
            continue
        winner = min(containing, key=lambda t: _area(t["bbox"]))
        tid = int(winner["tracker_id"])
        dist = f.get("match_distance")
        dist = float(dist) if isinstance(dist, (int, float)) else 1.0
        # If two faces fall in the same track this frame, keep the closer match.
        prev = out.get(tid)
        if prev is None or dist < prev["match_distance"]:
            out[tid] = {
                "person_id": str(pid),
                "person_name": (str(f["person_name"]) if f.get("person_name") else None),
                "match_distance": dist,
            }
    return out


def assign_tracker_ids(person_tracks, faces) -> None:
    """Stamp each face with the ``tracker_id`` of the tightest person track box
    whose region contains the face centre. Mutates the face dicts in place,
    setting ``face["tracker_id"]`` (left unset when no track contains it).

    Unlike :func:`bind_faces_to_tracks` this runs *before* recognition, for
    every face (matched or not), so the pipeline can pool a track's face
    embeddings into one stable identity decision."""
    tracks = [
        t
        for t in (person_tracks or [])
        if t.get("tracker_id") is not None and _valid_box(t.get("bbox"))
    ]
    if not tracks:
        return
    for f in faces or []:
        fb = f.get("bbox")
        if not _valid_box(fb):
            continue
        fc = _center(fb)
        containing = [t for t in tracks if _inside(fc, t["bbox"])]
        if not containing:
            continue
        winner = min(containing, key=lambda t: _area(t["bbox"]))
        f["tracker_id"] = int(winner["tracker_id"])


class IdentityBinder:
    """Stateful per-camera binder that holds bindings across keyframes.

    Call ``update`` once per processed keyframe with that camera's tracked person
    detections and matched faces. Query ``identity_for`` to get the held identity of a
    track even on frames where its face is not visible. Bindings expire ``ttl`` seconds
    after a track was last seen, so a reused tracker_id cannot inherit a stale person.
    """

    def __init__(self, ttl: float = DEFAULT_TTL_SECONDS):
        self.ttl = ttl
        # camera_id -> {tracker_id -> Binding}
        self._state: dict[str, dict[int, Binding]] = {}

    def update(
        self,
        camera_id,
        person_tracks,
        faces,
        *,
        now: float | None = None,
        handoff: dict[str, dict] | None = None,
    ) -> dict[int, dict]:
        """Fold this keyframe's face hits into the held bindings and expire stale ones.
        Returns the current ``{tracker_id: identity}`` for tracks present this frame, where
        identity is ``{person_id, person_name, body_cluster_id, state, bound_by}`` and
        ``state`` is one of ``person`` | ``body`` | ``unknown``.

        ``handoff`` is an optional ``{body_cluster_id: {person_id, person_name}}`` map
        resolved elsewhere (see :mod:`services.perception.identity_handoff`), used to
        recover the identity of a track arriving on a camera it has no local binding on.
        Passed in rather than fetched here so this class stays synchronous and pure: the
        binding contract remains testable without Redis, a pipeline, or a database."""
        now = time.monotonic() if now is None else now
        cam = str(camera_id)
        held = self._state.setdefault(cam, {})

        present_ids: set[int] = set()
        present_track_box: dict[int, list] = {}
        present_body: dict[int, str] = {}
        # Tracks whose Person identity came from body re-identification
        # rather than from a face this frame. reid stamps these onto the
        # detection as person_id + person_via="body".
        present_body_person: dict[int, dict] = {}
        for t in person_tracks or []:
            tid = t.get("tracker_id")
            if tid is None or not _valid_box(t.get("bbox")):
                continue
            tid = int(tid)
            present_ids.add(tid)
            present_track_box[tid] = t["bbox"]
            if t.get("body_cluster_id"):
                present_body[tid] = str(t["body_cluster_id"])
            if t.get("person_via") == "body" and t.get("person_id"):
                present_body_person[tid] = {
                    "person_id": str(t["person_id"]),
                    "person_name": (
                        str(t["person_name"]) if t.get("person_name") else None
                    ),
                }

        # 1. Apply this frame's face->track bindings (closer match can overwrite).
        fresh = bind_faces_to_tracks(person_tracks, faces)
        for tid, info in fresh.items():
            prev = held.get(tid)
            if prev is None or info["match_distance"] <= prev.match_distance:
                held[tid] = Binding(
                    person_id=info["person_id"],
                    person_name=info["person_name"],
                    last_seen=now,
                    match_distance=info["match_distance"],
                )

        # 2. Expire stale bindings FIRST, using last_seen from prior frames. A track absent
        #    longer than ttl loses its identity, so a reappearing or reused tracker_id never
        #    inherits a stale person. Face hits in step 1 already refreshed last_seen, so a
        #    genuinely-present person is never wrongly expired.
        for tid in list(held):
            if now - held[tid].last_seen > self.ttl:
                del held[tid]

        # 3. Refresh last_seen for held tracks still present this frame. Continuous presence
        #    holds the binding through face occlusion (the v1 weakness this fixes).
        for tid in present_ids:
            if tid in held:
                held[tid].last_seen = now

        # 4. Build the per-track identity view for tracks present this frame.
        result: dict[int, dict] = {}
        for tid in present_ids:
            b = held.get(tid)
            if b is not None:
                result[tid] = {
                    "person_id": b.person_id,
                    "person_name": b.person_name,
                    "body_cluster_id": present_body.get(tid),
                    "state": "person",
                    # A face landed on this track THIS frame, versus a
                    # binding held from an earlier one. Same claim, made
                    # at different distances from the evidence.
                    "bound_by": "face" if tid in fresh else "held",
                }
                continue

            # 4b. No face binding, but body re-identification resolved this
            # track's cluster to a Person on an earlier frame. That is a
            # real identity claim and was being thrown away (issue #146):
            # reid stamps person_id on the detection and the binder
            # reported state="body", person_id=None.
            #
            # Deliberately NOT written into ``held``. A face binding is
            # authoritative and persists; this one is recomputed from the
            # body evidence on every frame, so it disappears the moment the
            # appearance match does rather than outliving it.
            # 4c. Nothing local, but this track's body cluster was bound to a
            # Person on another camera (or before a restart) recently enough
            # to still be the same visit. This is the cross-camera hand-off:
            # a lookup instead of waiting for a fresh face (issue #147).
            #
            # Ranked below 4b because reid's cluster link is a deliberate,
            # face-confirmed database record, while this is a recent binding
            # that happens to still be inside its TTL. They agree in every
            # ordinary case; when they disagree, prefer the recorded one.
            via_body = present_body_person.get(tid)
            if via_body is None:
                bc = present_body.get(tid)
                handed = (handoff or {}).get(bc) if bc else None
                if handed and handed.get("person_id"):
                    result[tid] = {
                        "person_id": str(handed["person_id"]),
                        "person_name": handed.get("person_name"),
                        "body_cluster_id": bc,
                        "state": "person",
                        "bound_by": "handoff",
                    }
                    continue

            if via_body is not None:
                result[tid] = {
                    "person_id": via_body["person_id"],
                    "person_name": via_body["person_name"],
                    "body_cluster_id": present_body.get(tid),
                    "state": "person",
                    "bound_by": "body",
                }
            elif tid in present_body:
                result[tid] = {
                    "person_id": None,
                    "person_name": None,
                    "body_cluster_id": present_body[tid],
                    "state": "body",
                    "bound_by": "body",
                }
            else:
                result[tid] = {
                    "person_id": None,
                    "person_name": None,
                    "body_cluster_id": None,
                    "state": "unknown",
                    "bound_by": None,
                }
        return result

    def identity_for(self, camera_id, tracker_id) -> dict | None:
        """The held identity for a track, or None if unbound. Does not expire here; call
        ``update`` to drive expiry.

        Face-derived only. Body-derived identities are recomputed per frame inside
        ``update`` and are deliberately not held, so they never appear here."""
        b = self._state.get(str(camera_id), {}).get(int(tracker_id))
        if b is None:
            return None
        return {
            "person_id": b.person_id,
            "person_name": b.person_name,
            "state": "person",
            "bound_by": "held",
        }

    def reset(self, camera_id=None) -> None:
        if camera_id is None:
            self._state.clear()
        else:
            self._state.pop(str(camera_id), None)


# The rungs whose identity came from a face, directly or held from an earlier
# frame on the same track. Only these may be published to the cross-camera
# hand-off map. A binding recovered FROM the map ("handoff") or inferred from
# appearance alone ("body") is excluded on purpose: if a lookup could write
# itself back, an identity would refresh its own TTL every time it was read and
# would never expire, which is exactly how a wrong identity becomes permanent.
PUBLISHABLE_RUNGS = frozenset({"face", "held"})


def writes_for(identities) -> dict[str, dict]:
    """The hand-off entries a frame's identities may publish.

    Takes the ``{tracker_id: identity}`` mapping ``IdentityBinder.update``
    returns and produces ``{body_cluster_id: {person_id, person_name}}`` for
    the face-derived bindings that carry a body cluster. Pure, for tests."""
    out: dict[str, dict] = {}
    for ident in (identities or {}).values():
        if not ident:
            continue
        if ident.get("bound_by") not in PUBLISHABLE_RUNGS:
            continue
        bc = ident.get("body_cluster_id")
        pid = ident.get("person_id")
        if not bc or not pid:
            continue
        out[str(bc)] = {
            "person_id": str(pid),
            "person_name": ident.get("person_name"),
        }
    return out
