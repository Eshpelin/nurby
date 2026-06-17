"""Security regression tests for issue #35.

Three hardening surfaces against SSRF / arbitrary file access through the
ffmpeg + camera-URL pipeline (mirrors Frigate PR #23478 + #22607):

1. Structural ffmpeg *flag allowlist* (a blocklist proved bypassable) —
   shared.ffmpeg_safe.assert_allowed_args.
2. Path *containment* for every recording path that reaches ffmpeg —
   shared.ffmpeg_safe.contained_input (reuses shared.paths.resolve_inside).
3. SSRF *host block* for server-fetched http_snapshot / http_mjpeg / hls
   camera URLs — shared.netpolicy.stream_target_rejection_sync.

Legit inputs (real codec flags, in-root recordings, public camera hosts)
must keep working.
"""

import os

import pytest

from shared.ffmpeg_safe import (
    ALLOWED_FLAGS,
    PROTOCOL_WHITELIST_ARGS,
    DisallowedFfmpegArgError,
    assert_allowed_args,
    contained_input,
)
from shared.netpolicy import stream_target_rejection_sync

# ── 1. ffmpeg flag allowlist ─────────────────────────────────────────


def test_legit_trim_command_allowed():
    cmd = [
        "ffmpeg", *PROTOCOL_WHITELIST_ARGS,
        "-hide_banner", "-loglevel", "warning", "-y",
        "-ss", "1.500", "-i", "/recordings/cam/a.mp4", "-t", "5.000",
        "-c", "copy", "-movflags", "+faststart", "/recordings/out.mp4",
    ]
    assert_allowed_args(cmd)  # must not raise


def test_legit_reencode_command_allowed():
    cmd = [
        "ffmpeg", *PROTOCOL_WHITELIST_ARGS,
        "-hide_banner", "-loglevel", "warning", "-y",
        "-i", "/recordings/a.mp4",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        "/recordings/out.mp4",
    ]
    assert_allowed_args(cmd)


def test_frame_extract_command_allowed():
    cmd = [
        "ffmpeg", *PROTOCOL_WHITELIST_ARGS,
        "-hide_banner", "-loglevel", "error",
        "-ss", "3.000", "-i", "/recordings/a.mp4",
        "-frames:v", "1", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    ]
    assert_allowed_args(cmd)


def test_disallowed_flag_rejected():
    # -filter_script reads its filtergraph from an arbitrary file (read).
    cmd = ["ffmpeg", "-i", "/recordings/a.mp4", "-filter_script", "/etc/passwd", "out.mp4"]
    with pytest.raises(DisallowedFfmpegArgError):
        assert_allowed_args(cmd)


def test_attachment_dump_flag_rejected():
    # -dump_attachment:t writes attachment data to an arbitrary file (write).
    cmd = ["ffmpeg", "-dump_attachment:t", "/root/.ssh/authorized_keys", "-i", "in.mkv"]
    with pytest.raises(DisallowedFfmpegArgError):
        assert_allowed_args(cmd)


def test_bare_dash_argument_rejected():
    # Frigate's bypass smuggled option files via a bare '-'.
    cmd = ["ffmpeg", "-i", "in.mp4", "-", "out.mp4"]
    with pytest.raises(DisallowedFfmpegArgError):
        assert_allowed_args(cmd)


def test_protocol_whitelist_value_is_not_treated_as_flag():
    # "file" / "file,pipe,crypto" are values, not flags.
    assert_allowed_args(["ffmpeg", "-protocol_whitelist", "file", "-i", "a.mp4", "o.mp4"])


def test_allowed_flags_is_frozenset_of_dash_tokens():
    assert ALLOWED_FLAGS
    assert all(f.startswith("-") for f in ALLOWED_FLAGS)


# ── 2. path containment ──────────────────────────────────────────────


def _make_root(tmp_path):
    root = tmp_path / "recordings"
    root.mkdir()
    return root


def test_in_root_relative_path_resolves(tmp_path):
    root = _make_root(tmp_path)
    cam = root / "cam1"
    cam.mkdir()
    f = cam / "clip.mp4"
    f.write_bytes(b"x")
    # Stored as a "recordings/<cam>/<file>" relative path.
    got = contained_input("recordings/cam1/clip.mp4", str(root))
    assert got == os.path.realpath(str(f))


def test_bare_relative_path_resolves(tmp_path):
    root = _make_root(tmp_path)
    f = root / "clip.mp4"
    f.write_bytes(b"x")
    got = contained_input("clip.mp4", str(root))
    assert got == os.path.realpath(str(f))


def test_absolute_in_root_path_resolves(tmp_path):
    root = _make_root(tmp_path)
    f = root / "clip.mp4"
    f.write_bytes(b"x")
    got = contained_input(str(f), str(root))
    assert got == os.path.realpath(str(f))


def test_dotdot_escape_rejected(tmp_path):
    root = _make_root(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"x")
    assert contained_input("../secret.txt", str(root)) is None


def test_absolute_outside_root_rejected(tmp_path):
    root = _make_root(tmp_path)
    assert contained_input("/etc/passwd", str(root)) is None


def test_symlink_escape_rejected(tmp_path):
    root = _make_root(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"x")
    link = root / "evil.mp4"
    os.symlink(str(secret), str(link))
    # Stored value points at the in-root symlink, but it resolves outside.
    assert contained_input("evil.mp4", str(root)) is None


def test_empty_path_returns_none(tmp_path):
    root = _make_root(tmp_path)
    assert contained_input("", str(root)) is None
    assert contained_input(None, str(root)) is None


# ── 3. SSRF host block for stream URLs ───────────────────────────────


def test_public_camera_url_allowed():
    assert stream_target_rejection_sync("https://cam.example.com/snap.jpg") is None
    assert stream_target_rejection_sync("http://203.0.113.5/mjpeg") is None


def test_loopback_always_refused():
    assert stream_target_rejection_sync("http://127.0.0.1/snap.jpg") is not None
    assert stream_target_rejection_sync("http://[::1]:8080/snap") is not None
    # Even with block_private off (loopback is unconditional).
    assert stream_target_rejection_sync("http://127.0.0.1/x", block_private=False) is not None


def test_link_local_always_refused():
    assert stream_target_rejection_sync("http://169.254.1.1/snap") is not None


def test_cloud_metadata_always_refused():
    assert stream_target_rejection_sync("http://169.254.169.254/latest/meta-data/") is not None
    assert stream_target_rejection_sync("http://metadata.google.internal/x") is not None


def test_lan_camera_allowed_by_default():
    # RFC1918 is a legitimate LAN camera on a self-hosted box.
    assert stream_target_rejection_sync("http://192.168.1.50/snap.jpg") is None
    assert stream_target_rejection_sync("http://10.0.0.7/mjpeg") is None
    assert stream_target_rejection_sync("http://172.16.5.5/hls.m3u8") is None


def test_lan_camera_refused_when_block_private_enabled():
    assert stream_target_rejection_sync("http://192.168.1.50/snap.jpg", block_private=True) is not None
    assert stream_target_rejection_sync("http://10.0.0.7/mjpeg", block_private=True) is not None
    assert stream_target_rejection_sync("http://172.16.5.5/hls", block_private=True) is not None


def test_block_private_still_allows_public():
    assert stream_target_rejection_sync("https://cam.example.com/x", block_private=True) is None


def test_garbage_url_refused():
    assert stream_target_rejection_sync("not-a-url") is not None
    assert stream_target_rejection_sync("") is not None
