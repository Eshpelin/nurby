"""Tests for per-camera per-object-class VLM prompt guidance.

Nurby's VLM is scene-level (one call per keyframe over all detections),
so Frigate's per-tracked-object ``object_prompts`` (PR #13767) is adapted
by unioning the guidance snippets for whichever configured labels are
present in the frame. These tests cover that pure helper plus the
CameraUpdate schema round-trip.
"""

from services.perception.vlm import build_object_guidance
from shared.schemas import CameraUpdate


def _dets(*labels):
    return [{"label": l, "confidence": 0.9} for l in labels]


def test_no_config_or_no_detections_returns_empty():
    assert build_object_guidance(_dets("person"), None) == ""
    assert build_object_guidance(_dets("person"), {}) == ""
    assert build_object_guidance(None, {"person": "x"}) == ""
    assert build_object_guidance([], {"person": "x"}) == ""


def test_only_present_labels_are_injected():
    prompts = {"person": "describe clothing", "car": "note plate region"}
    out = build_object_guidance(_dets("person"), prompts)
    assert "person: describe clothing" in out
    assert "car" not in out  # car configured but not in frame


def test_multiple_present_labels_unioned():
    prompts = {"person": "clothing", "car": "make and colour"}
    out = build_object_guidance(_dets("person", "car"), prompts)
    assert "person: clothing" in out
    assert "car: make and colour" in out


def test_case_insensitive_match():
    out = build_object_guidance(_dets("Person"), {"PERSON": "clothing"})
    assert "person: clothing" in out


def test_license_plate_skipped():
    out = build_object_guidance(_dets("license_plate"), {"license_plate": "x"})
    assert out == ""


def test_duplicate_labels_emitted_once():
    out = build_object_guidance(_dets("person", "person"), {"person": "clothing"})
    assert out.count("person: clothing") == 1


def test_blank_guidance_values_ignored():
    out = build_object_guidance(_dets("person", "car"), {"person": "   ", "car": "colour"})
    assert "person" not in out
    assert "car: colour" in out


def test_unconfigured_present_label_skipped():
    out = build_object_guidance(_dets("dog"), {"person": "clothing"})
    assert out == ""


def test_camera_update_schema_accepts_object_prompts():
    body = CameraUpdate(vlm_object_prompts={"person": "describe clothing"})
    dumped = body.model_dump(exclude_unset=True)
    assert dumped == {"vlm_object_prompts": {"person": "describe clothing"}}


def test_camera_update_omits_object_prompts_when_unset():
    body = CameraUpdate(vlm_prompt="hi")
    assert "vlm_object_prompts" not in body.model_dump(exclude_unset=True)
