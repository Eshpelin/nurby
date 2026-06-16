"""Stream URL scheme validation.

Replicates Frigate PR #23352 (accept rtsps://) and closes the file:// / gopher://
SSRF + arbitrary-file injection surface for network camera types, while leaving
path-based types (usb, file) untouched.
"""

import pytest
from pydantic import ValidationError

from shared.schemas import CameraCreate, CameraUpdate, validate_stream_url


def _create(**kw):
    base = dict(name="cam", stream_url="rtsp://host/stream", stream_type="rtsp")
    base.update(kw)
    return CameraCreate(**base)


def test_rtsp_and_rtsps_allowed():
    _create(stream_url="rtsp://h/s", stream_type="rtsp")
    _create(stream_url="rtsps://h/s", stream_type="rtsp")  # Frigate #23352
    _create(stream_url="rtsps://h/s", stream_type="webcam")


def test_http_types_allow_http_and_https():
    _create(stream_url="http://h/snap.jpg", stream_type="http_snapshot")
    _create(stream_url="https://h/snap.jpg", stream_type="http_mjpeg")
    _create(stream_url="https://h/index.m3u8", stream_type="hls")


def test_path_types_skip_scheme_check():
    _create(stream_url="0", stream_type="usb")
    _create(stream_url="/dev/video0", stream_type="usb")
    _create(stream_url="/recordings/clip.mp4", stream_type="file")


def test_file_scheme_rejected_for_network_type():
    with pytest.raises(ValidationError):
        _create(stream_url="file:///etc/passwd", stream_type="rtsp")


def test_dangerous_schemes_rejected_for_http_type():
    for url in ("gopher://h/x", "dict://h:11211/x", "file:///etc/passwd"):
        with pytest.raises(ValidationError):
            _create(stream_url=url, stream_type="http_snapshot")


def test_rtsp_type_rejects_plain_http():
    with pytest.raises(ValidationError):
        _create(stream_url="http://h/s", stream_type="rtsp")


def test_update_partial_without_type_tolerates_path_and_network():
    CameraUpdate(stream_url="rtsps://h/s")
    CameraUpdate(stream_url="/recordings/x.mp4")  # bare path: cannot infer type


def test_update_partial_rejects_dangerous_scheme():
    with pytest.raises(ValidationError):
        CameraUpdate(stream_url="file:///etc/passwd")


def test_helper_direct():
    assert validate_stream_url("rtsps://h/s", "rtsp") == "rtsps://h/s"
    assert validate_stream_url("/dev/video0", "usb") == "/dev/video0"
    with pytest.raises(ValueError):
        validate_stream_url("file:///x", "rtsp")
