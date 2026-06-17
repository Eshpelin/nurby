"""Credential injection into stream URLs (build_auth_url).

Replicates Frigate PRs #4259 / #4057 / #4646: camera passwords routinely
contain reserved URL characters (@ : / # ? %). They must be percent-encoded
before being embedded in the netloc, otherwise ffmpeg/urlparse split the
netloc at the wrong character and resolve the wrong host (the camera never
connects). All credential-injection call sites route through this one
function, so encoding here covers stream worker, mediamtx mux, audio
sub-stream, and the live camera-test endpoint.
"""

from urllib.parse import unquote, urlparse

from services.ingestion.stream import build_auth_url


def test_no_username_returns_url_unchanged():
    assert build_auth_url("rtsp://host:554/live", None, None) == "rtsp://host:554/live"
    assert build_auth_url("rtsp://host:554/live", "", "secret") == "rtsp://host:554/live"


def test_simple_credentials_unchanged_by_encoding():
    # Alphanumeric creds must round-trip identically (backward compatible).
    url = build_auth_url("rtsp://192.168.0.2:554/live", "admin", "pass123")
    assert url == "rtsp://admin:pass123@192.168.0.2:554/live"


def test_special_characters_are_percent_encoded():
    url = build_auth_url("rtsp://192.168.0.2:554/live", "admin", "p@ss/w#rd")
    # The host must still parse as the camera, not a fragment of the password.
    parsed = urlparse(url)
    assert parsed.hostname == "192.168.0.2"
    assert parsed.port == 554
    assert parsed.username == "admin"
    # urlparse leaves %XX encoded; unquoting recovers the original password.
    assert unquote(parsed.password) == "p@ss/w#rd"
    # The raw URL must not contain the bare reserved chars in the cred portion.
    assert "p@ss/w#rd" not in url
    assert "%40" in url and "%2F" in url and "%23" in url


def test_username_with_special_chars_encoded():
    url = build_auth_url("rtsp://h:554/s", "user@domain", "pw")
    parsed = urlparse(url)
    assert unquote(parsed.username) == "user@domain"
    assert parsed.hostname == "h"
    assert "user@domain@" not in url  # the literal @ in the user is encoded


def test_no_port_preserved():
    url = build_auth_url("rtsp://host/live", "admin", "secret")
    assert url == "rtsp://admin:secret@host/live"


def test_http_scheme_supported():
    url = build_auth_url("http://cam/snapshot.jpg", "admin", "a:b@c")
    parsed = urlparse(url)
    assert parsed.scheme == "http"
    assert parsed.hostname == "cam"
    assert unquote(parsed.password) == "a:b@c"
