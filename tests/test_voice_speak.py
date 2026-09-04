"""The speak action, its policy gate, and the transport layer (#155).

The policy half is where the consequences are: every one of these
refusals is a camera choosing not to make a noise in somebody's house, so
the refusals are tested at least as hard as the successes.
"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services.voice import policy as policy_mod
from services.voice import rtp
from services.voice.auth import basic_header, digest_response, parse_challenge
from services.voice.policy import (
    MAX_UTTERANCE_SECONDS,
    clamp_volume,
    in_quiet_hours,
    may_speak,
    parse_hhmm,
    within_duration_budget,
)
from services.voice.speaker import resolve_transport_kind
from services.voice.transport import build_transport, known_kinds
from services.voice.transport.onvif_backchannel import absolute_control
from services.voice.transport.vendor_http import camera_base_url


def _camera(**kw):
    base = dict(
        id="cam-1", name="Front Door", stream_url="rtsp://1.2.3.4:554/s",
        username="admin", password=None,
        speaker_enabled=True, speaker_transport=None, speaker_voice=None,
        speaker_volume=70, speaker_quiet_start=None, speaker_quiet_end=None,
        speaker_cooldown_seconds=30, speaker_daily_cap=50,
        speaker_endpoint=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _capability(**kw):
    base = dict(supported=True, transport="onvif_backchannel", codec="pcmu",
                sample_rate=8000, probe_error=None)
    base.update(kw)
    return SimpleNamespace(**base)


NOON = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


def _gate(**kw):
    args = dict(
        camera=_camera(), text="please step back", now=NOON,
        household_enabled=True, estop_engaged=False, capability=_capability(),
        spoken_today=0, seconds_since_last=None, tz_name="UTC",
    )
    args.update(kw)
    return may_speak(**args)


# ---- the gate ------------------------------------------------------------


def test_a_configured_camera_may_speak():
    assert _gate().allowed is True


def test_a_paused_household_never_speaks():
    """estop is pause-new-work, and making a noise in someone's house is
    exactly the kind of new work it exists to stop."""
    decision = _gate(estop_engaged=True)
    assert decision.allowed is False
    assert decision.reason == "estop"


def test_voice_off_household_wide_wins_over_a_camera_being_enabled():
    assert _gate(household_enabled=False).reason == "disabled"


def test_a_camera_with_voice_off_stays_quiet():
    assert _gate(camera=_camera(speaker_enabled=False)).reason == "disabled"


def test_an_empty_render_blames_the_template_not_the_hardware():
    """Checked before capability so a broken template reports itself."""
    decision = _gate(text="   ")
    assert decision.reason == "empty_text"


def test_a_camera_that_cannot_speak_is_refused_with_the_probe_s_reason():
    decision = _gate(capability=_capability(
        supported=False, probe_error="camera advertises no backchannel"))
    assert decision.reason == "unsupported"
    assert "backchannel" in decision.detail


def test_an_unprobed_camera_is_allowed_through():
    """Absence of a probe is not evidence of absence. The transport will
    report the truth soon enough, and refusing here would mean a camera
    never speaks until someone remembers to run a sweep."""
    assert _gate(capability=None).allowed is True


# ---- quiet hours ---------------------------------------------------------


def test_quiet_hours_wrapping_midnight():
    """The normal configuration. A naive start <= t <= end comparison
    matches nothing here and silently disables quiet hours entirely."""
    late = datetime(2026, 8, 29, 23, 30, tzinfo=timezone.utc)
    early = datetime(2026, 8, 29, 3, 0, tzinfo=timezone.utc)
    midday = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)

    assert in_quiet_hours(late, "22:00", "07:00") is True
    assert in_quiet_hours(early, "22:00", "07:00") is True
    assert in_quiet_hours(midday, "22:00", "07:00") is False


def test_quiet_hours_within_one_day():
    at_two = datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc)
    assert in_quiet_hours(at_two, "13:00", "15:00") is True
    assert in_quiet_hours(NOON, "13:00", "15:00") is False


def test_quiet_hours_are_local():
    """02:00 UTC is 08:00 in Dhaka, which is outside a 22:00-07:00
    window even though it is inside it in UTC."""
    at_two_utc = datetime(2026, 8, 29, 2, 0, tzinfo=timezone.utc)
    assert in_quiet_hours(at_two_utc, "22:00", "07:00", "UTC") is True
    assert in_quiet_hours(at_two_utc, "22:00", "07:00", "Asia/Dhaka") is False


def test_a_zero_length_window_means_no_quiet_hours():
    assert in_quiet_hours(NOON, "22:00", "22:00") is False


def test_unset_or_malformed_quiet_hours_do_not_silence_a_camera():
    """Degrading to "no quiet hours" is right: failing closed would make
    a typo silently disable every announcement in the house."""
    assert in_quiet_hours(NOON, None, "07:00") is False
    assert in_quiet_hours(NOON, "not a time", "07:00") is False
    assert parse_hhmm("25:99") is not None or parse_hhmm("oops") is None


def test_the_camera_window_overrides_the_household_one():
    decision = _gate(
        camera=_camera(speaker_quiet_start="11:00", speaker_quiet_end="13:00"),
        household_quiet_start="22:00", household_quiet_end="07:00",
    )
    assert decision.reason == "quiet_hours"


def test_the_household_window_applies_when_the_camera_has_none():
    decision = _gate(
        now=datetime(2026, 8, 29, 23, 0, tzinfo=timezone.utc),
        household_quiet_start="22:00", household_quiet_end="07:00",
    )
    assert decision.reason == "quiet_hours"


# ---- rate limits ---------------------------------------------------------


def test_cooldown_stops_a_rule_shouting_at_the_same_visitor():
    decision = _gate(seconds_since_last=5.0)
    assert decision.reason == "cooldown"


def test_speaking_again_after_the_cooldown_is_fine():
    assert _gate(seconds_since_last=45.0).allowed is True


def test_the_daily_cap_is_enforced():
    assert _gate(spoken_today=50).reason == "daily_cap"
    assert _gate(spoken_today=49).allowed is True


def test_a_zero_cap_or_cooldown_means_unlimited():
    camera = _camera(speaker_cooldown_seconds=0, speaker_daily_cap=0)
    assert _gate(camera=camera, seconds_since_last=0.1, spoken_today=999).allowed


# ---- volume --------------------------------------------------------------


def test_every_ceiling_applies_and_the_lowest_wins():
    """A rule must not be able to raise a camera above what the household
    set, so a misconfigured template cannot wake the street."""
    assert clamp_volume(100, 60, 80) == 60
    assert clamp_volume(100, 90, 50) == 50
    assert clamp_volume(30, 90, 80) == 30


def test_no_requested_volume_uses_the_ceiling():
    assert clamp_volume(None, 60, 80) == 60


def test_volume_never_exceeds_the_absolute_maximum():
    assert clamp_volume(500, None, None) == policy_mod.MAX_VOLUME


def test_a_nonsense_volume_falls_back_rather_than_muting():
    assert clamp_volume(-5, 70, None) == 70
    assert clamp_volume("loud", 70, None) == 70


# ---- utterance length ----------------------------------------------------


def test_a_runaway_utterance_is_refused():
    """A template that interpolated a whole VLM description would hold
    the speaker for minutes."""
    assert within_duration_budget(MAX_UTTERANCE_SECONDS + 1).allowed is False
    assert within_duration_budget(3.0).allowed is True


# ---- transport selection -------------------------------------------------


def test_an_explicit_setting_beats_the_probe():
    """A household who knows their camera better than the probe did
    should be able to say so."""
    camera = _camera(speaker_transport="hikvision")
    assert resolve_transport_kind(camera, _capability()) == "hikvision"


def test_the_probed_transport_is_used_by_default():
    assert resolve_transport_kind(_camera(), _capability()) == "onvif_backchannel"


def test_an_external_speaker_is_the_fallback():
    """The path that works regardless of what the camera can do."""
    camera = _camera(speaker_endpoint="http://pi.local/say")
    assert resolve_transport_kind(camera, _capability(supported=False)) == "http_device"


def test_nothing_known_means_nothing_to_try():
    assert resolve_transport_kind(_camera(), _capability(supported=False)) is None


def test_every_transport_kind_can_be_built():
    for kind in known_kinds():
        assert asyncio.run(build_transport(kind)) is not None


def test_tapo_says_what_to_do_instead_rather_than_failing_blankly():
    from services.voice.transport import TransportUnsupported

    transport = asyncio.run(build_transport("tapo"))
    with pytest.raises(TransportUnsupported) as caught:
        asyncio.run(transport.speak(_camera(), b"x", codec="pcmu", sample_rate=8000))

    assert "external speaker" in str(caught.value)


# ---- RTP -----------------------------------------------------------------


def test_packets_are_twenty_milliseconds_of_audio():
    """Cameras are built around 20 ms frames and often drop larger ones."""
    payload = b"\xff" * 8000  # one second of 8 kHz G.711
    packets = rtp.packetize(payload, "pcmu", 8000)

    assert len(packets) == 50
    assert len(packets[0]) == 12 + 160  # header plus one frame


def test_the_first_packet_marks_the_talkspurt():
    packets = rtp.packetize(b"\xff" * 320, "pcmu", 8000)
    assert rtp.parse_header(packets[0])["marker"] is True
    assert rtp.parse_header(packets[1])["marker"] is False


def test_sequence_numbers_increment_and_timestamps_advance_by_samples():
    """Advancing the timestamp by bytes rather than samples plays L16 at
    double speed, which is the classic version of this bug."""
    packets = rtp.packetize(b"\x00" * 640, "l16", 8000)
    first = rtp.parse_header(packets[0])
    second = rtp.parse_header(packets[1])

    assert second["sequence"] == first["sequence"] + 1
    assert second["timestamp"] - first["timestamp"] == 160  # samples, not bytes


def test_payload_types_are_the_static_rfc_numbers():
    assert rtp.payload_type("pcmu") == 0
    assert rtp.payload_type("pcma") == 8
    with pytest.raises(ValueError):
        rtp.payload_type("opus")


def test_all_packets_share_one_ssrc():
    packets = rtp.packetize(b"\xff" * 1600, "pcmu", 8000)
    ssrcs = {rtp.parse_header(p)["ssrc"] for p in packets}
    assert len(ssrcs) == 1


def test_empty_audio_produces_no_packets():
    assert rtp.packetize(b"", "pcmu", 8000) == []


def test_interleaved_framing_matches_the_rtsp_spec():
    framed = rtp.interleave(b"abcd", channel=0)
    assert framed[0:1] == b"$"
    assert framed[1] == 0
    assert int.from_bytes(framed[2:4], "big") == 4
    assert framed[4:] == b"abcd"


# ---- auth ----------------------------------------------------------------


def test_a_digest_challenge_is_parsed():
    header = 'Digest realm="IP Camera", nonce="abc123", qop="auth", algorithm=MD5'
    challenge = parse_challenge(header)

    assert challenge["realm"] == "IP Camera"
    assert challenge["nonce"] == "abc123"


def test_a_basic_only_challenge_yields_nothing_to_work_with():
    assert parse_challenge('Basic realm="cam"') == {}
    assert parse_challenge("") == {}


def test_digest_is_deterministic_for_a_fixed_cnonce():
    """Same inputs, same hash. A camera rejecting a correct password is
    otherwise impossible to debug."""
    challenge = parse_challenge('Digest realm="r", nonce="n", qop="auth"')
    args = dict(username="admin", password="pw", method="DESCRIBE",
                uri="rtsp://cam/s", challenge=challenge, cnonce="fixed")

    assert digest_response(**args) == digest_response(**args)
    assert 'username="admin"' in digest_response(**args)


def test_digest_without_qop_still_works():
    """Older cameras omit qop entirely and reject a response that
    includes nc and cnonce."""
    challenge = parse_challenge('Digest realm="r", nonce="n"')
    header = digest_response(username="a", password="b", method="SETUP",
                             uri="/s", challenge=challenge)
    assert "qop" not in header
    assert "nc=" not in header


def test_an_incomplete_challenge_produces_nothing_rather_than_garbage():
    assert digest_response(username="a", password="b", method="X", uri="/",
                           challenge={}) is None


def test_an_unsupported_algorithm_is_refused_loudly():
    """Sending an MD5 hash where SHA-256 was asked for just fails at the
    camera with no explanation."""
    challenge = parse_challenge('Digest realm="r", nonce="n", algorithm=SHA-256')
    assert digest_response(username="a", password="b", method="X", uri="/",
                           challenge=challenge) is None


def test_basic_header_is_still_available():
    assert basic_header("admin", "pw").startswith("Basic ")


# ---- URL handling --------------------------------------------------------


def test_control_urls_come_in_three_shapes():
    base = "rtsp://cam/stream"
    assert absolute_control(base, "rtsp://cam/stream/trackID=3") == "rtsp://cam/stream/trackID=3"
    assert absolute_control(base, "trackID=3") == "rtsp://cam/stream/trackID=3"
    assert absolute_control(base, "*") == base
    assert absolute_control(base, None) == base


def test_the_vendor_http_base_is_derived_from_the_stream_url():
    """Cameras are configured by their stream URL and rarely carry a
    separate HTTP address."""
    assert camera_base_url(_camera()) == "http://1.2.3.4:80"


def test_a_camera_with_no_host_is_unsupported_rather_than_a_crash():
    from services.voice.transport import TransportUnsupported

    with pytest.raises(TransportUnsupported):
        camera_base_url(_camera(stream_url="not-a-url"))
