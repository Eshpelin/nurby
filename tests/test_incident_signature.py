"""Identity resolution behind the incident signature (issue #144).

The signature decides what counts as "the same subject", and everything
downstream inherits it: Incident.signature_key, then Journey.subject_key,
then every agent query about a person. These tests pin the ladder so a
subject cannot silently stop being themselves the moment their face turns
away, which is the regression this module exists to prevent.
"""

from services.perception.incident_tracker import (
    compute_signature,
    compute_signature_detail,
    resolve_subjects,
)


def _track(tid, *, state, person_id=None, person_name=None, body_cluster_id=None):
    return {
        "tracker_id": tid,
        "bbox": [0, 0, 10, 20],
        "person_id": person_id,
        "person_name": person_name,
        "body_cluster_id": body_cluster_id,
        "state": state,
    }


def _face(*, person_name=None, cluster_id=None):
    return {
        "bbox": [1, 1, 5, 5],
        "person_id": "p-1" if person_name else None,
        "person_name": person_name,
        "match_distance": 0.4,
        "cluster_id": cluster_id,
    }


# ---- the core regression -------------------------------------------------


def test_held_binding_survives_the_face_going_away():
    """The frame where the face is visible and the frame right after it,
    where the binder still holds the identity, must produce the SAME
    signature. Before #144 the second frame fell through to motion."""
    with_face = {
        "faces": [_face(person_name="Ahmed")],
        "bodies": [],
        "tracks": [_track(1, state="person", person_id="p-1", person_name="Ahmed",
                          body_cluster_id="bc-1")],
    }
    face_turned_away = {
        "faces": [],
        "bodies": [{"bbox": [0, 0, 10, 20], "body_cluster_id": "bc-1"}],
        "tracks": [_track(1, state="person", person_id="p-1", person_name="Ahmed",
                          body_cluster_id="bc-1")],
    }
    assert compute_signature(with_face, None) == ("person", "Ahmed")
    assert compute_signature(face_turned_away, None) == ("person", "Ahmed")


def test_body_cluster_keeps_a_subject_out_of_motion():
    """No face and no held person, but body re-id matched a cluster. That
    is a continuous subject, not ambient motion."""
    pd = {
        "faces": [],
        "bodies": [{"bbox": [0, 0, 10, 20], "body_cluster_id": "bc-9"}],
        "tracks": [_track(3, state="body", body_cluster_id="bc-9")],
    }
    objects = {"objects": [{"label": "person"}]}
    assert compute_signature(pd, objects) == ("body", "bc-9")


def test_unmatched_body_still_falls_through_to_objects():
    """A person box with no body cluster at all carries no identity, so
    the old object/motion behaviour must survive."""
    pd = {"faces": [], "bodies": [], "tracks": [_track(4, state="unknown")]}
    objects = {"objects": [{"label": "person"}]}
    assert compute_signature(pd, objects) == ("object", "person")


# ---- ladder ordering -----------------------------------------------------


def test_face_cluster_outranks_body_cluster():
    """A face cluster survives a change of clothes; an appearance
    embedding does not. When both are present the durable one wins."""
    pd = {
        "faces": [_face(cluster_id="fc-1")],
        "bodies": [{"bbox": [0, 0, 1, 1], "body_cluster_id": "bc-1"}],
        "tracks": [_track(1, state="body", body_cluster_id="bc-1")],
    }
    kind, key = compute_signature(pd, None)
    assert (kind, key) == ("cluster", "fc-1")


def test_named_person_outranks_everything():
    pd = {
        "faces": [_face(person_name="Sara"), _face(cluster_id="fc-2")],
        "bodies": [{"bbox": [0, 0, 1, 1], "body_cluster_id": "bc-2"}],
        "tracks": [_track(1, state="person", person_id="p-2", person_name="Sara",
                          body_cluster_id="bc-2")],
    }
    assert compute_signature(pd, None) == ("person", "Sara")


# ---- resolve_subjects ----------------------------------------------------


def test_resolve_subjects_dedupes_track_and_face_for_one_person():
    """The same person arrives twice, once via the held track and once via
    the matched face. That is one subject, not two."""
    pd = {
        "faces": [_face(person_name="Ahmed")],
        "bodies": [],
        "tracks": [_track(1, state="person", person_id="p-1", person_name="Ahmed")],
    }
    subjects = resolve_subjects(pd)
    assert [s["key"] for s in subjects] == ["Ahmed"]
    # The held rung is recorded first, so that is the evidence reported.
    assert subjects[0]["bound_by"] == "held"


def test_resolve_subjects_orders_by_ladder_then_key():
    pd = {
        "faces": [_face(person_name="Sara"), _face(cluster_id="fc-1")],
        "bodies": [{"bbox": [0, 0, 1, 1], "body_cluster_id": "bc-1"}],
        "tracks": [],
    }
    assert [s["kind"] for s in resolve_subjects(pd)] == ["person", "cluster", "body"]


def test_resolve_subjects_tolerates_legacy_payloads():
    """Observations written before ``tracks`` existed carry only faces."""
    pd = {"faces": [_face(person_name="Ahmed")], "count": 1}
    subjects = resolve_subjects(pd)
    assert [(s["kind"], s["key"], s["bound_by"]) for s in subjects] == [
        ("person", "Ahmed", "face")
    ]


def test_resolve_subjects_empty_inputs():
    assert resolve_subjects(None) == []
    assert resolve_subjects({}) == []
    assert resolve_subjects({"faces": [], "bodies": [], "tracks": []}) == []


def test_held_track_without_a_name_keys_on_the_person_id():
    """A binding we cannot render a name for is still a stable subject.
    Collapsing it to unknown would restart the incident every frame."""
    pd = {"faces": [], "bodies": [], "tracks": [
        _track(1, state="person", person_id="p-77", person_name=None)
    ]}
    assert compute_signature(pd, None) == ("person", "p-77")


# ---- bound_by ------------------------------------------------------------


def test_detail_reports_the_evidence_rung():
    face_only = {"faces": [_face(person_name="Ahmed")], "bodies": [], "tracks": []}
    assert compute_signature_detail(face_only, None) == ("person", "Ahmed", "face")

    body_only = {"faces": [], "bodies": [], "tracks": [
        _track(2, state="body", body_cluster_id="bc-5")
    ]}
    assert compute_signature_detail(body_only, None) == ("body", "bc-5", "body")


def test_detail_reports_no_rung_for_non_identities():
    objects = {"objects": [{"label": "car"}]}
    assert compute_signature_detail(None, objects) == ("object", "car", None)
    assert compute_signature_detail(None, None) == ("motion", "motion", None)


# ---- unchanged behaviour -------------------------------------------------


def test_unknown_face_signature_unchanged():
    pd = {"faces": [_face()], "bodies": [], "tracks": []}
    assert compute_signature(pd, None) == ("unknown", "unknown")


def test_object_labels_capped_at_three():
    objects = {"objects": [{"label": lbl} for lbl in ("car", "dog", "cat", "bird")]}
    kind, key = compute_signature(None, objects)
    assert kind == "object"
    assert len(key.split(",")) == 3


def test_inert_scene_is_motion():
    assert compute_signature(None, {"objects": [{"label": "couch"}]}) == (
        "motion", "motion",
    )
