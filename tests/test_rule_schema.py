"""Parity tests for the rules schema registry (shared/rule_schema.py).

The registry mirrors two other sources of truth: the frontend's
TRIGGER_TYPES list (frontend/src/components/rules/types.tsx) and the
backend action allowlist (shared.schemas._VALID_ACTION_TYPES). These
tests fail when one side drifts.
"""

from shared.rule_schema import (
    ACTION_TYPES,
    CONDITION_FIELDS,
    SEQUENCE_SCHEMA,
    TRIGGER_TYPES,
    build_schema,
)
from shared.schemas import _VALID_ACTION_TYPES

# Transcribed from frontend/src/components/rules/types.tsx TRIGGER_TYPES.
FRONTEND_TRIGGER_TYPES = [
    "object_detected",
    "findanything",
    "vehicle_detected",
    "face_detected",
    "face_recognized",
    "face_unknown",
    "motion",
    "audio_event",
    "clap_pattern",
    "speech_phrase",
    "loitering",
    "line_cross",
    "camera_offline",
    "camera_online",
    "incident_started",
    "incident_ended",
    "plate_list",
    "parking_violation",
    "wrong_way",
    "speed_over",
    "red_light_cross",
    "crosswalk_violation",
    "lane_occupancy",
    "any",
]


def test_frontend_trigger_types_all_registered():
    assert len(FRONTEND_TRIGGER_TYPES) == 24
    registered = {t["type"] for t in TRIGGER_TYPES}
    missing = set(FRONTEND_TRIGGER_TYPES) - registered
    assert not missing, f"frontend trigger types missing from registry: {sorted(missing)}"


def test_no_unknown_trigger_types_registered():
    extra = {t["type"] for t in TRIGGER_TYPES} - set(FRONTEND_TRIGGER_TYPES)
    assert not extra, f"registry has trigger types the frontend does not know: {sorted(extra)}"


def test_action_types_match_backend_allowlist():
    registered = {a["type"] for a in ACTION_TYPES}
    assert registered == set(_VALID_ACTION_TYPES)


def test_entries_have_label_description_group_fields():
    for entry in TRIGGER_TYPES + ACTION_TYPES:
        for key in ("label", "description", "group"):
            assert isinstance(entry.get(key), str) and entry[key].strip(), (
                f"{entry.get('type')}: empty or missing '{key}'"
            )
        assert isinstance(entry.get("fields"), list), f"{entry.get('type')}: fields must be a list"


def test_fields_are_well_formed():
    allowed_types = {"string", "number", "boolean", "uuid", "enum", "points", "list", "object"}
    allowed_refs = {"camera", "person", "telegram_channel"}
    entries = TRIGGER_TYPES + ACTION_TYPES
    all_fields = [f for e in entries for f in e["fields"]] + CONDITION_FIELDS
    all_fields += SEQUENCE_SCHEMA["fields"] + SEQUENCE_SCHEMA["step_fields"]
    for f in all_fields:
        assert f.get("name"), f"field without name: {f}"
        assert f.get("type") in allowed_types, f"{f['name']}: bad type {f.get('type')}"
        assert isinstance(f.get("required"), bool), f"{f['name']}: required must be bool"
        if "ref" in f:
            assert f["ref"] in allowed_refs, f"{f['name']}: bad ref {f['ref']}"
        if f["type"] == "enum":
            assert f.get("enum"), f"{f['name']}: enum field needs an enum list"


def _fields_by_name(trigger_type: str) -> dict:
    entry = next(t for t in TRIGGER_TYPES if t["type"] == trigger_type)
    return {f["name"]: f for f in entry["fields"]}


def test_geometry_triggers_declare_points_and_camera():
    # Matches shared.schemas._validate_trigger_pattern: loitering and
    # line_cross reject saves without points + camera_id (legacy
    # zone_name mode aside).
    for trigger_type in ("loitering", "line_cross"):
        fields = _fields_by_name(trigger_type)
        assert "points" in fields and fields["points"]["required"] is True
        assert fields["points"]["type"] == "points"
        assert "camera_id" in fields and fields["camera_id"]["required"] is True
        assert fields["camera_id"]["ref"] == "camera"


def test_speech_phrase_requires_phrases():
    fields = _fields_by_name("speech_phrase")
    assert fields["phrases"]["required"] is True


def test_sequence_schema_shape():
    field_names = {f["name"] for f in SEQUENCE_SCHEMA["fields"]}
    assert {"steps", "correlate_by", "on_refire", "max_active", "cameras", "on_timeout"} <= field_names
    correlate = next(f for f in SEQUENCE_SCHEMA["fields"] if f["name"] == "correlate_by")
    assert set(correlate["enum"]) == {"person", "journey", "incident", "camera", "none"}
    refire = next(f for f in SEQUENCE_SCHEMA["fields"] if f["name"] == "on_refire")
    assert set(refire["enum"]) == {"ignore", "restart"}
    step_names = {f["name"] for f in SEQUENCE_SCHEMA["step_fields"]}
    assert {"check", "within_seconds", "confirm_frames", "negate", "pre_gate"} <= step_names


def test_condition_fields_match_engine():
    # Names read by RuleEngine._check_conditions plus the veto override.
    names = {f["name"] for f in CONDITION_FIELDS}
    assert names == {
        "camera_id", "camera_ids", "days", "time_after", "time_before",
        "min_confidence", "ignore_veto",
    }


def test_build_schema_keys():
    schema = build_schema()
    assert set(schema) == {"triggers", "actions", "conditions", "sequence"}
