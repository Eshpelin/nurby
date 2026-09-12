"""Voice policy presets and how the UI reports capability (#156).

The presets are the product and the raw numbers are the escape hatch, so
what matters here is that a preset means something coherent, that a
camera which drifts off one says so, and that the capability panel never
implies we know something we do not.
"""

from types import SimpleNamespace

from services.api.routes.voice import _camera_view, _capability_view
from services.voice.presets import (
    CONCIERGE,
    CUSTOM,
    DETERRENT,
    SILENT,
    get,
    infer,
    listing,
    matches,
)


def _camera(**kw):
    base = dict(
        id="cam-1", name="Front Door",
        speaker_enabled=False, speaker_transport=None, speaker_voice=None,
        speaker_volume=70, speaker_quiet_start=None, speaker_quiet_end=None,
        speaker_cooldown_seconds=30, speaker_daily_cap=50,
        speaker_endpoint=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _with(preset_key):
    return _camera(**get(preset_key).as_settings())


# ---- the presets mean something -----------------------------------------


def test_silent_is_actually_silent():
    assert get(SILENT).speaker_enabled is False


def test_the_other_presets_can_speak():
    assert get(DETERRENT).speaker_enabled is True
    assert get(CONCIERGE).speaker_enabled is True


def test_a_deterrent_is_louder_and_rarer_than_a_concierge():
    """They are different products sharing a mechanism. A warning is
    occasional and firm; a greeting is quieter and more frequent."""
    deterrent, concierge = get(DETERRENT), get(CONCIERGE)

    assert deterrent.speaker_volume > concierge.speaker_volume
    assert deterrent.speaker_cooldown_seconds > concierge.speaker_cooldown_seconds
    assert deterrent.speaker_daily_cap < concierge.speaker_daily_cap


def test_a_concierge_cooldown_is_short_enough_to_hold_a_doorstep_exchange():
    """A visitor who says two things should not be answered once."""
    assert get(CONCIERGE).speaker_cooldown_seconds <= 20


def test_every_speaking_preset_has_quiet_hours():
    for key in (DETERRENT, CONCIERGE):
        preset = get(key)
        assert preset.speaker_quiet_start and preset.speaker_quiet_end


def test_unknown_and_custom_resolve_to_nothing():
    assert get(CUSTOM) is None
    assert get("nonsense") is None
    assert get(None) is None


def test_lookup_is_forgiving_about_case():
    assert get("  Deterrent ") is get(DETERRENT)


# ---- inference -----------------------------------------------------------


def test_a_camera_matching_a_preset_reports_it():
    for key in (SILENT, DETERRENT, CONCIERGE):
        assert infer(_with(key)) == key


def test_a_camera_that_drifted_reports_custom():
    """Editing a number directly must not leave the UI claiming a preset
    the camera no longer matches."""
    drifted = _camera(**{**get(DETERRENT).as_settings(), "speaker_volume": 42})
    assert infer(drifted) == CUSTOM


def test_matches_checks_every_field_not_just_enabled():
    preset = get(DETERRENT)
    almost = _camera(**{**preset.as_settings(), "speaker_daily_cap": 999})
    assert matches(almost, preset) is False


# ---- what is offered -----------------------------------------------------


def test_silent_is_offered_first():
    """A camera that can talk should start out not talking."""
    assert listing()[0]["key"] == SILENT


def test_custom_is_offered_last_and_carries_no_settings():
    last = listing()[-1]
    assert last["key"] == CUSTOM
    assert last["settings"] == {}


def test_every_offered_preset_explains_itself():
    for entry in listing():
        assert entry["label"].strip()
        assert len(entry["description"]) > 20


# ---- the capability panel ------------------------------------------------


def test_never_probed_is_not_the_same_as_unsupported():
    """A household deserves to know which one it is looking at before
    concluding their camera is mute."""
    view = _capability_view(None)

    assert view["probed"] is False
    assert view["supported"] is None
    assert "Not checked yet" in view["summary"]


def test_a_supported_camera_names_its_transport():
    view = _capability_view(SimpleNamespace(
        supported=True, transport="onvif_backchannel", codec="pcmu",
        sample_rate=8000, vendor="hikvision", probed_at=None, probe_error=None,
    ))

    assert view["supported"] is True
    assert "onvif_backchannel" in view["summary"]


def test_an_unsupported_camera_repeats_the_probe_s_own_reason():
    """More useful than a generic "cannot play audio", and it is the
    string that tells someone whether to try a different transport."""
    view = _capability_view(SimpleNamespace(
        supported=False, transport="none", vendor="tapo", probed_at=None,
        probe_error="camera advertises no backchannel",
    ))

    assert view["supported"] is False
    assert view["summary"] == "camera advertises no backchannel"


def test_an_unsupported_camera_with_no_reason_still_says_something():
    view = _capability_view(SimpleNamespace(
        supported=False, transport="none", vendor=None, probed_at=None,
        probe_error=None,
    ))
    assert view["summary"].strip()


# ---- the camera view -----------------------------------------------------


def test_the_view_reports_the_inferred_preset():
    view = _camera_view(_with(DETERRENT), None)
    assert view["preset"] == DETERRENT


def test_the_endpoint_is_reported_as_a_boolean_not_a_value():
    """It can carry a token, so the UI is told whether one is set and
    never shown what it is."""
    view = _camera_view(_camera(speaker_endpoint="http://pi.local/say?key=secret"), None)

    assert view["speaker_endpoint"] is True
    assert "secret" not in str(view)


def test_the_view_carries_the_settings_the_page_edits():
    view = _camera_view(_camera(), None)
    for field in (
        "speaker_enabled", "speaker_volume", "speaker_quiet_start",
        "speaker_quiet_end", "speaker_cooldown_seconds", "speaker_daily_cap",
    ):
        assert field in view


# ---- the conversation transcript (issue #157) ---------------------------


def _heard(at, text):
    return SimpleNamespace(started_at=at, text=text)


def _said(at, text, status="played", reason=None):
    return SimpleNamespace(
        created_at=at, text=text, status=status, suppressed_reason=reason
    )


def test_both_halves_of_a_conversation_are_merged_in_time_order():
    """The two sides come from different systems and neither knows about
    the other, so the merge happens here."""
    from datetime import datetime, timezone

    from services.api.routes.voice import interleave_transcript

    t0 = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 9, 5, 10, 0, 5, tzinfo=timezone.utc)
    t2 = datetime(2026, 9, 5, 10, 0, 9, tzinfo=timezone.utc)

    turns = interleave_transcript(
        heard=[_heard(t1, "I have a parcel")],
        said=[_said(t0, "Hello, this is an automated doorbell."),
              _said(t2, "You can leave it by the door.")],
    )

    assert [t["speaker"] for t in turns] == ["camera", "visitor", "camera"]
    assert turns[1]["text"] == "I have a parcel"


def test_a_suppressed_line_is_kept_and_labelled():
    """Dropping it would make a filtered conversation look like an
    ordinary one, which is the opposite of an audit."""
    from datetime import datetime, timezone

    from services.api.routes.voice import interleave_transcript

    turns = interleave_transcript(
        heard=[],
        said=[_said(datetime(2026, 9, 5, tzinfo=timezone.utc),
                    "Sorry, I can't help.", status="suppressed",
                    reason="absence")],
    )

    assert turns[0]["status"] == "suppressed"
    assert turns[0]["suppressed_reason"] == "absence"


def test_an_empty_conversation_is_an_empty_list():
    from services.api.routes.voice import interleave_transcript

    assert interleave_transcript([], []) == []
    assert interleave_transcript(None, None) == []


def test_a_row_without_a_timestamp_does_not_crash_the_sort():
    """Sorts first rather than raising. A missing timestamp is a data
    oddity, not a reason to fail the whole transcript."""
    from datetime import datetime, timezone

    from services.api.routes.voice import interleave_transcript

    turns = interleave_transcript(
        heard=[_heard(None, "no timestamp")],
        said=[_said(datetime(2026, 9, 5, tzinfo=timezone.utc), "later")],
    )

    assert turns[0]["text"] == "no timestamp"
