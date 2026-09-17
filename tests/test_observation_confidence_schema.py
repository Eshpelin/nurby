"""Real observation confidence + schema-constrained caption fields (#221).

Covers the two honesty fixes:

1. Observation.confidence is a real detector-derived value, never a fabricated
   constant. The strongest object detection's score is used; a motion-only frame
   yields None (no signal), not a placeholder.
2. Any machine-consumed caption field is schema-validated with defined
   parse-failure behavior: a bad field is dropped, never guessed.
"""

import pathlib

import pytest

from services.perception import caption_schema as cs


# ── validate_confidence ───────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    (0.0, 0.0),
    (0.5, 0.5),
    (1.0, 1.0),
    ("0.73", 0.73),
    (1.2, 1.0),      # finite over-range clamps (detector rounding)
    (-0.1, 0.0),     # finite under-range clamps
])
def test_validate_confidence_valid_and_clamped(raw, expected):
    assert cs.validate_confidence(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", [None, "", "abc", object(), float("nan"), float("inf"), float("-inf")])
def test_validate_confidence_garbage_is_none(raw):
    assert cs.validate_confidence(raw) is None


# ── detection_confidence ──────────────────────────────────────────────────────

def test_detection_confidence_picks_strongest():
    dets = [
        {"label": "person", "confidence": 0.42},
        {"label": "car", "confidence": 0.91},
        {"label": "dog", "confidence": 0.55},
    ]
    assert cs.detection_confidence(dets) == pytest.approx(0.91)


def test_detection_confidence_empty_is_none():
    assert cs.detection_confidence([]) is None
    assert cs.detection_confidence(None) is None


def test_detection_confidence_skips_unscored_and_garbage():
    dets = [
        {"label": "person"},                       # no confidence
        {"label": "car", "confidence": None},      # null confidence
        {"label": "x", "confidence": "not a num"}, # garbage
        "not a dict",
        {"label": "bike", "confidence": 0.33},
    ]
    assert cs.detection_confidence(dets) == pytest.approx(0.33)


def test_detection_confidence_all_unscored_is_none():
    assert cs.detection_confidence([{"label": "person"}, {"label": "car"}]) is None


# ── schema validation (defined parse-failure behavior) ────────────────────────

def test_caption_attributes_valid_subset():
    cleaned = cs.validate_caption_attributes(
        {"state": "active", "person_count": 3, "caption_confidence": 0.7}
    )
    assert cleaned == {"state": "active", "person_count": 3, "caption_confidence": 0.7}


def test_caption_attributes_drops_bad_enum():
    cleaned = cs.validate_caption_attributes({"state": "dancing", "person_count": 2})
    # Bad enum value dropped, the rest survives.
    assert "state" not in cleaned
    assert cleaned["person_count"] == 2


def test_caption_attributes_drops_out_of_range_and_negative():
    cleaned = cs.validate_caption_attributes(
        {"person_count": -1, "caption_confidence": 5.0, "state": "idle"}
    )
    assert "person_count" not in cleaned
    assert "caption_confidence" not in cleaned
    assert cleaned == {"state": "idle"}


def test_caption_attributes_strips_unknown_fields():
    cleaned = cs.validate_caption_attributes({"state": "empty", "injected": "evil"})
    assert cleaned == {"state": "empty"}


def test_validate_against_schema_required_missing_flags_not_ok():
    schema = {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["a", "b"]}},
        "required": ["action"],
        "additionalProperties": False,
    }
    ok, cleaned = cs.validate_against_schema({}, schema)
    assert ok is False
    assert cleaned == {}


def test_validate_against_schema_rejects_bool_as_integer():
    schema = {
        "type": "object",
        "properties": {"n": {"type": "integer", "minimum": 0}},
        "additionalProperties": False,
    }
    ok, cleaned = cs.validate_against_schema({"n": True}, schema)
    assert ok is False
    assert "n" not in cleaned


def test_validate_against_schema_non_dict_is_invalid():
    ok, cleaned = cs.validate_against_schema("nope", cs.CAPTION_ATTRIBUTE_SCHEMA)
    assert ok is False and cleaned == {}


# ── no fabricated confidence constant remains (AC1 guard) ─────────────────────

def test_vlm_queue_has_no_fabricated_confidence_constant():
    src = pathlib.Path(__file__).resolve().parents[1] / "services" / "perception" / "vlm_queue.py"
    text = src.read_text()
    assert "obs.confidence = 0.8" not in text, (
        "The hardcoded 0.8 observation confidence must not return (#221)."
    )
