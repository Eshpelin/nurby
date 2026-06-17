"""Structural hardening for user-influenced ffmpeg invocations.

ffmpeg is a confused deputy: every command we build interpolates a
``Recording.file_path`` (operator-supplied, stored in the DB) as an input
and writes an output under our media roots. ffmpeg also treats inputs as
*protocols*, not files (``-i concat:…``, ``-i tee:…``, ``-i pipe:``,
``-i http://…``), and accepts file-backed option values (``-filter_script
/etc/passwd``, ``-/option file``), so a poisoned path or a smuggled flag
turns a clip build into arbitrary file read/write or SSRF.

Frigate originally shipped a *blocklist* of dangerous ffmpeg tokens and it
proved bypassable (stream-specifier filters, scheme-less protocols,
tee/preset/option-file access). Frigate PR #23478 replaced it with a
structural *allowlist*; PR #22607 added path containment + an input
protocol whitelist. This module mirrors both:

* :data:`ALLOWED_FLAGS` — every ffmpeg flag any of our invocations may use.
  Anything off-list is rejected by :func:`assert_allowed_args`. New flags
  must be added here deliberately (and audited) rather than slipping in.
* :func:`contained_input` — resolves a stored recording path through
  ``shared.paths.resolve_inside`` so no ``..`` / absolute / symlink escape
  reaches ffmpeg. Replaces the permissive ``_resolve_path`` fallbacks.
* :data:`PROTOCOL_WHITELIST_ARGS` — ``-protocol_whitelist file`` (plus the
  ones the concat demuxer legitimately needs) to forbid ffmpeg from
  opening network / pipe protocols on the local-file read paths.

These cover the *local recording read/transcode* paths
(``services/agent/analyzer.py``, ``services/perception/conversation_clip.py``,
``services/perception/vlm_enrichment_worker.py``,
``services/api/recording_annotate.py``, ``services/guardian/video.py``).
Live network capture (RTSP/HTTP) is a different surface guarded by the
scheme allowlist (shared/schemas.py) and SSRF host block
(shared/netpolicy.py).
"""

from __future__ import annotations

import os

from shared.paths import resolve_inside

__all__ = [
    "ALLOWED_FLAGS",
    "PROTOCOL_WHITELIST_ARGS",
    "PROTOCOL_WHITELIST_CONCAT_ARGS",
    "DisallowedFfmpegArgError",
    "assert_allowed_args",
    "contained_input",
]


class DisallowedFfmpegArgError(ValueError):
    """An ffmpeg argument is not on the structural allowlist."""


# Structural allowlist of ffmpeg flags we permit on user-influenced
# invocations. This is the complete set used across every local-recording
# read/transcode call site; extend it deliberately (and re-audit) when a
# new call site needs a flag. Anything not listed here is refused.
#
# Grouped for review:
#   logging / global   : -hide_banner -loglevel -y -nostdin -progress
#   protocol guard     : -protocol_whitelist -f -safe -fflags
#   seek / trim        : -ss -t -to -i -frames:v
#   video / audio codec: -c -c:v -c:a -an -vn -preset -crf -q:v -qscale:v
#   container / output : -movflags -pix_fmt -map -vf -vsync -r -shortest
#   image piping       : -vcodec -update
ALLOWED_FLAGS: frozenset[str] = frozenset(
    {
        # logging / global
        "-hide_banner",
        "-loglevel",
        "-y",
        "-nostdin",
        "-progress",
        # input protocol guard
        "-protocol_whitelist",
        "-f",
        "-safe",
        "-fflags",
        # seek / trim / input
        "-ss",
        "-t",
        "-to",
        "-i",
        "-frames:v",
        # video / audio codecs and quality
        "-c",
        "-c:v",
        "-c:a",
        "-an",
        "-vn",
        "-preset",
        "-crf",
        "-q:v",
        "-qscale:v",
        # container / output muxing
        "-movflags",
        "-pix_fmt",
        "-map",
        "-vf",
        "-vsync",
        "-r",
        "-shortest",
        # image piping (single-frame extraction)
        "-vcodec",
        "-update",
    }
)

# Applied right after the ``ffmpeg`` token on local-file read paths: forbid
# ffmpeg from opening any input protocol other than plain files. Closes the
# ``-i http://…`` (SSRF) and ``-i pipe:`` / ``-i concat:…`` levers.
PROTOCOL_WHITELIST_ARGS: tuple[str, ...] = ("-protocol_whitelist", "file")

# The concat *demuxer* (``-f concat -i list.txt``) reads a playlist file and
# then opens the segment files it names, which ffmpeg routes through the
# ``file`` + ``pipe`` protocols internally; ``crypto`` covers AES-encrypted
# segments. Network protocols stay excluded.
PROTOCOL_WHITELIST_CONCAT_ARGS: tuple[str, ...] = (
    "-protocol_whitelist",
    "file,pipe,crypto",
)


def assert_allowed_args(cmd: list[str]) -> None:
    """Reject an ffmpeg command line containing any flag off the allowlist.

    ``cmd`` is the full argv (including the leading ``ffmpeg``). Tokens that
    start with ``-`` are treated as flags and must be in
    :data:`ALLOWED_FLAGS`; everything else is a value (path, codec name,
    timestamp, …) and is not flag-checked here — path values are contained
    separately via :func:`contained_input`. The bare token ``-`` (stdin
    placeholder) and the ``pipe:N`` / ``-`` style outputs are never emitted
    by our call sites, and a literal ``-`` flag is refused because Frigate's
    bypass used ``-`` to smuggle option files.

    Raises :class:`DisallowedFfmpegArgError` on the first offending flag.
    """
    for tok in cmd:
        if not tok.startswith("-"):
            continue
        if tok == "-":
            raise DisallowedFfmpegArgError("bare '-' argument is not allowed")
        if tok not in ALLOWED_FLAGS:
            raise DisallowedFfmpegArgError(f"ffmpeg flag {tok!r} is not on the allowlist")


def contained_input(stored: str | None, allowed_dir: str) -> str | None:
    """Resolve a stored recording path to an absolute disk path, but only
    when it lands inside ``allowed_dir`` (after symlink resolution).

    Replaces the permissive ``_resolve_path`` fallbacks that accepted any
    absolute path or unbounded relative path. Returns ``None`` when the path
    is empty or escapes the root, so callers degrade to "no clip" rather
    than reading an arbitrary file. Mirrors the strip-prefix behavior of the
    old resolvers so existing DB rows (``recordings/<cam>/<file>.mp4``,
    ``./recordings/…``, bare relative, or already-absolute-inside-root)
    still resolve.
    """
    if not stored:
        return None
    base = os.path.abspath(allowed_dir)

    candidates: list[str] = []
    if os.path.isabs(stored):
        candidates.append(stored)
    else:
        rel = stored
        for prefix in ("./recordings/", "recordings/", "./"):
            if rel.startswith(prefix):
                rel = rel[len(prefix):]
                break
        candidates.append(os.path.join(base, rel))
        # Also try the raw value joined to the root, in case the stored path
        # already carries a camera-id prefix without the "recordings/" head.
        candidates.append(os.path.join(base, stored))

    for cand in candidates:
        resolved = resolve_inside(cand, base)
        if resolved is not None:
            return resolved
    return None
