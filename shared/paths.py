"""Filesystem containment for media-serving endpoints.

Recordings, thumbnails, audio captures, and person photos are served straight
off disk from paths stored in the database. Every such endpoint must prove the
resolved file actually lives inside its designated storage root before opening
it, so a poisoned database row or a stray symlink can never read files outside
the media directories.
"""

import os

__all__ = ["resolve_inside", "escape_like", "safe_getsize"]


def safe_getsize(path: str | os.PathLike | None) -> int:
    """File size in bytes, or ``0`` if the file is missing or ``stat`` fails.

    Replaces the ``os.path.exists(p) and os.path.getsize(p)`` idiom, which has a
    TOCTOU race (the file can vanish between the two calls) and, on network
    mounts, can raise transient ``OSError`` (e.g. ``Errno 121 Remote I/O``) that
    crashes the worker. A single guarded ``getsize`` degrades to ``0`` instead.
    """
    if not path:
        return 0
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def resolve_inside(path: str | None, allowed_dir: str) -> str | None:
    """Resolve ``path`` (following symlinks) and return its absolute form only
    when it lands inside ``allowed_dir``. Returns ``None`` otherwise.

    A plain ``startswith`` prefix check is not enough: it admits sibling
    directories (``/data/recordings-evil`` matches ``/data/recordings``) and
    follows symlinks blindly. ``realpath`` + ``commonpath`` closes both holes.
    """
    if not path:
        return None
    resolved = os.path.realpath(path)
    base = os.path.realpath(allowed_dir)
    try:
        if os.path.commonpath([resolved, base]) != base:
            return None
    except ValueError:
        # Mixed absolute/relative paths or different drives (Windows).
        return None
    return resolved


_LIKE_SPECIALS = ("\\", "%", "_")


def escape_like(value: str) -> str:
    """Escape SQL LIKE/ILIKE metacharacters in a user-supplied needle.

    The needle is still passed as a bound parameter (no SQL injection), but an
    unescaped ``%`` or ``_`` lets callers widen a filter beyond the literal
    text they asked for. Use together with ``.ilike(pattern, escape="\\\\")``.
    """
    for ch in _LIKE_SPECIALS:
        value = value.replace(ch, "\\" + ch)
    return value
