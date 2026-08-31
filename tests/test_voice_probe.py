"""Speaker capability probing (issue #153).

Whether a camera can be made to speak is the whole risk of the voice
feature. These tests cover the parsing against recorded responses, which
is the half that can be checked without hardware. The IO half is thin on
purpose for exactly that reason.

The direction of the backchannel is the thing most worth pinning: an SDP
audio section marked ``a=recvonly`` is the camera's MICROPHONE, and
pushing speech at it would fail silently in the most confusing possible
way.
"""

import asyncio
from types import SimpleNamespace

import pytest

from services.voice.probe import (
    ONVIF_BACKCHANNEL,
    PREFERRED_CODECS,
    TRANSPORT_NONE,
    TRANSPORT_ONVIF,
    build_describe,
    infer_vendor,
    parse_backchannel_sdp,
    probe_camera,
    rtsp_status,
    split_response,
    usable_codec,
)

# A camera that offers a backchannel: video down, microphone down, and a
# third section we may send into. Shaped after a real ONVIF response.
SDP_WITH_BACKCHANNEL = """v=0
o=- 1109162014219182 0 IN IP4 192.168.1.64
s=Media Presentation
c=IN IP4 0.0.0.0
t=0 0
m=video 0 RTP/AVP 96
a=control:rtsp://192.168.1.64/Streaming/Channels/101/trackID=1
a=rtpmap:96 H264/90000
a=recvonly
m=audio 0 RTP/AVP 0
a=control:rtsp://192.168.1.64/Streaming/Channels/101/trackID=2
a=rtpmap:0 PCMU/8000
a=recvonly
m=audio 0 RTP/AVP 0
a=control:rtsp://192.168.1.64/Streaming/Channels/101/trackID=3
a=rtpmap:0 PCMU/8000
a=sendonly
"""

# The same camera without the Require header honoured: video and mic only.
SDP_NO_BACKCHANNEL = """v=0
o=- 1109162014219182 0 IN IP4 192.168.1.64
s=Media Presentation
m=video 0 RTP/AVP 96
a=control:trackID=1
a=rtpmap:96 H264/90000
a=recvonly
m=audio 0 RTP/AVP 0
a=control:trackID=2
a=rtpmap:0 PCMU/8000
a=recvonly
"""


# ---- the direction trap --------------------------------------------------


def test_the_backchannel_is_the_sendonly_section():
    channel = parse_backchannel_sdp(SDP_WITH_BACKCHANNEL)

    assert channel is not None
    assert channel["codec"] == "pcmu"
    assert channel["sample_rate"] == 8000
    # trackID=3, the sendonly one. NOT trackID=2, which is the microphone.
    assert channel["control"].endswith("trackID=3")


def test_a_microphone_only_camera_offers_no_backchannel():
    """recvonly audio is the camera talking to us. Treating it as a
    speaker would push audio at a track that never plays it."""
    assert parse_backchannel_sdp(SDP_NO_BACKCHANNEL) is None


def test_video_only_cameras_are_not_mistaken_for_speakers():
    sdp = "v=0\nm=video 0 RTP/AVP 96\na=rtpmap:96 H264/90000\na=sendonly\n"
    assert parse_backchannel_sdp(sdp) is None


def test_empty_or_junk_sdp_is_survivable():
    assert parse_backchannel_sdp("") is None
    assert parse_backchannel_sdp("not an sdp at all") is None
    assert parse_backchannel_sdp(None) is None


# ---- codec negotiation ---------------------------------------------------


def test_a_preferred_codec_wins_over_one_we_cannot_produce():
    """A camera offering AAC first and G.711 second is usable; picking
    the first listed would have made it look like it was not."""
    sdp = """m=audio 0 RTP/AVP 104 0
a=rtpmap:104 MPEG4-GENERIC/16000
a=rtpmap:0 PCMU/8000
a=sendonly
"""
    assert parse_backchannel_sdp(sdp)["codec"] == "pcmu"


def test_an_unusable_codec_is_reported_rather_than_hidden():
    sdp = """m=audio 0 RTP/AVP 104
a=rtpmap:104 MPEG4-GENERIC/16000
a=sendonly
"""
    channel = parse_backchannel_sdp(sdp)
    assert channel["codec"] == "mpeg4-generic"
    assert usable_codec(channel["codec"]) is False


def test_stereo_and_rate_are_read_when_present():
    sdp = "m=audio 0 RTP/AVP 10\na=rtpmap:10 L16/44100/2\na=sendonly\n"
    channel = parse_backchannel_sdp(sdp)

    assert channel["sample_rate"] == 44100
    assert channel["channels"] == 2


def test_channels_default_to_mono():
    sdp = "m=audio 0 RTP/AVP 8\na=rtpmap:8 PCMA/8000\na=sendonly\n"
    assert parse_backchannel_sdp(sdp)["channels"] == 1


def test_what_we_can_actually_produce():
    assert usable_codec("pcmu") is True
    assert usable_codec("PCMA") is True
    assert usable_codec("opus") is False
    assert usable_codec(None) is False
    assert set(PREFERRED_CODECS) == {"pcmu", "pcma", "l16"}


# ---- the request ---------------------------------------------------------


def test_the_describe_asks_for_the_backchannel():
    """Without the Require header a camera answers with its normal
    stream and the probe would conclude, wrongly, that it cannot speak."""
    request = build_describe("rtsp://cam/stream1")

    assert f"Require: {ONVIF_BACKCHANNEL}" in request
    assert request.startswith("DESCRIBE rtsp://cam/stream1 RTSP/1.0")
    assert request.endswith("\r\n\r\n")


def test_credentials_are_included_when_present():
    request = build_describe("rtsp://cam/s", auth="Basic abc123")
    assert "Authorization: Basic abc123" in request


def test_no_auth_header_when_there_are_no_credentials():
    assert "Authorization" not in build_describe("rtsp://cam/s")


# ---- responses -----------------------------------------------------------


def test_status_parsing():
    assert rtsp_status("RTSP/1.0 200 OK\r\nCSeq: 1") == 200
    assert rtsp_status("RTSP/1.0 401 Unauthorized") == 401
    assert rtsp_status("garbage") is None
    assert rtsp_status("") is None


def test_head_and_body_split_on_either_line_ending():
    head, body = split_response("RTSP/1.0 200 OK\r\nCSeq: 1\r\n\r\nv=0\nm=audio")
    assert head.startswith("RTSP/1.0 200")
    assert body.startswith("v=0")

    head, body = split_response("RTSP/1.0 200 OK\nCSeq: 1\n\nv=0")
    assert body == "v=0"


def test_a_response_with_no_body_does_not_crash():
    head, body = split_response("RTSP/1.0 401 Unauthorized")
    assert body == ""


# ---- vendor inference ----------------------------------------------------


def test_vendors_are_recognised_from_the_stream_url():
    assert infer_vendor("rtsp://x/Streaming/Channels/101") == "hikvision"
    assert infer_vendor("rtsp://x/cam/realmonitor?channel=1") == "dahua"
    assert infer_vendor("rtsp://x/h264Preview_01_main") == "reolink"
    assert infer_vendor("rtsp://x/stream1") == "tapo"


def test_vendors_are_recognised_from_a_name():
    assert infer_vendor(None, "Hikvision Front Door") == "hikvision"


def test_an_unknown_vendor_is_none_rather_than_a_guess():
    assert infer_vendor("rtsp://192.168.1.5/onvif1") is None
    assert infer_vendor(None, None) is None
    assert infer_vendor("") is None


# ---- probing a camera ----------------------------------------------------


def _camera(url="rtsp://192.168.1.64/Streaming/Channels/101", **kw):
    base = dict(
        id="cam-1", name="Front Door", stream_url=url, stream_type="rtsp",
        username=None, password=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _run(coro):
    return asyncio.run(coro)


def _fake_describe(monkeypatch, status, body, head="RTSP/1.0 200 OK"):
    async def fake(stream_url, username=None, password=None, timeout=4.0):
        return status, head, body

    import services.voice.probe as probe_mod
    monkeypatch.setattr(probe_mod, "rtsp_describe", fake)


def test_a_camera_with_a_backchannel_is_supported(monkeypatch):
    _fake_describe(monkeypatch, 200, SDP_WITH_BACKCHANNEL)
    result = _run(probe_camera(_camera()))

    assert result.supported is True
    assert result.transport == TRANSPORT_ONVIF
    assert result.codec == "pcmu"
    assert result.vendor == "hikvision"
    assert result.error is None


def test_a_camera_without_one_is_a_finding_not_a_blank(monkeypatch):
    _fake_describe(monkeypatch, 200, SDP_NO_BACKCHANNEL)
    result = _run(probe_camera(_camera()))

    assert result.supported is False
    assert result.transport == TRANSPORT_NONE
    assert "no backchannel" in result.error
    # And it says where to look next for this vendor.
    assert "ISAPI" in result.detail["try_next"]


def test_a_tapo_gets_an_honest_explanation(monkeypatch):
    """Tapo does two-way audio over a proprietary HTTPS API, so a failed
    ONVIF probe is expected rather than a dead end."""
    _fake_describe(monkeypatch, 200, SDP_NO_BACKCHANNEL)
    result = _run(probe_camera(_camera("rtsp://192.168.10.126:554/stream1")))

    assert result.vendor == "tapo"
    assert "proprietary" in result.detail["try_next"]


def test_a_codec_we_cannot_produce_is_not_supported(monkeypatch):
    sdp = "m=audio 0 RTP/AVP 104\na=rtpmap:104 MPEG4-GENERIC/16000\na=sendonly\n"
    _fake_describe(monkeypatch, 200, sdp)
    result = _run(probe_camera(_camera()))

    assert result.transport == TRANSPORT_ONVIF  # it has one
    assert result.supported is False            # we just cannot use it
    assert "cannot produce" in result.error


def test_an_auth_failure_says_so(monkeypatch):
    _fake_describe(monkeypatch, 401, "", head="RTSP/1.0 401 Unauthorized")
    result = _run(probe_camera(_camera()))

    assert result.supported is False
    assert "authentication" in result.error


def test_an_unreachable_camera_does_not_stop_a_sweep(monkeypatch):
    async def boom(*a, **kw):
        raise OSError("no route to host")

    import services.voice.probe as probe_mod
    monkeypatch.setattr(probe_mod, "rtsp_describe", boom)

    result = _run(probe_camera(_camera()))

    assert result.supported is False
    assert "no route to host" in result.error
    assert result.detail["stage"] == "rtsp_describe"


def test_a_non_rtsp_camera_is_skipped_cleanly():
    result = _run(probe_camera(_camera("http://cam/snapshot.jpg", stream_type="http_snapshot")))

    assert result.supported is False
    assert "not an RTSP camera" in result.error


def test_the_raw_evidence_is_kept(monkeypatch):
    """So a later look does not have to re-run against hardware to know
    what was seen."""
    _fake_describe(monkeypatch, 200, SDP_WITH_BACKCHANNEL)
    result = _run(probe_camera(_camera()))

    assert result.detail["rtsp_status"] == 200
    assert "m=audio" in result.detail["sdp"]
