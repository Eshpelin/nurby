"""Evidence-bundle manifest generation (issue #225).

Pure, side-effect-free helpers that turn a set of exported media files into
an integrity manifest: a per-file SHA-256 over the bytes actually shipped,
plus the provenance a recipient (police, an insurer, the other side of a
Guardian custody handover) needs to trust the pile of MP4s.

Design notes:

* **Hash the shipped bytes, not the source.** The caller passes the exact
  file it puts in the zip. If the media was transcoded/annotated/blurred,
  the hash must attest to what the recipient holds, so hashing happens on
  the export artifact (see ``sha256_file``).
* **Label derived media.** Each entry carries a ``processing`` block. An
  original recording is ``{"kind": "original"}``; an annotated or blurred
  re-render is marked as derived and references the original by hash when
  it is retained, so nothing masquerades as untouched source footage.
* **Do not over-claim.** The manifest attests to what Nurby recorded and
  exported. It is not a legal chain of custody. That caveat ships inside
  the manifest itself (``_DISCLAIMER``) so it travels with the bundle.

The manifest is a pure function over rows, so it is unit-tested without a
database or disk (``build_manifest``); only ``sha256_file`` touches the
filesystem and is tested against a temp file.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

# The manifest schema version. Bump when the shape of an entry or the
# top-level block changes so a verifier can branch on it.
MANIFEST_VERSION = 1

# The file name the manifest is written under inside the bundle. A verifier
# looks for exactly this at the archive root.
MANIFEST_FILENAME = "manifest.json"

_DISCLAIMER = (
    "This manifest lists the SHA-256 hash and provenance of each file in this "
    "bundle as exported by Nurby. It attests to what Nurby recorded and to the "
    "exact bytes shipped in this bundle. It does NOT by itself establish a legal "
    "chain of custody, and it does not attest to events outside Nurby's "
    "recording. Verify each file by recomputing its SHA-256 and comparing it to "
    "the value listed here."
)

# Chunked so a multi-GB recording never loads whole into memory.
_HASH_CHUNK = 1024 * 1024


def sha256_file(path: str) -> str:
    """Return the hex SHA-256 of the bytes at ``path`` (streamed in chunks)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _iso(dt: datetime | None) -> str | None:
    """UTC ISO-8601 with a trailing Z, or None. Naive datetimes are assumed UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _local_iso(dt: datetime | None) -> str | None:
    """The wall-clock ISO-8601 as stored, preserving any local offset.

    Kept alongside the UTC value so a reader sees the time the way the
    scene's operator would have (and can spot a timezone mismatch)."""
    if dt is None:
        return None
    return dt.isoformat()


def manifest_entry(
    *,
    arcname: str,
    sha256: str,
    size_bytes: int,
    camera_id: uuid.UUID | str | None,
    camera_name: str | None,
    recording_id: uuid.UUID | str | None,
    started_at: datetime | None,
    ended_at: datetime | None,
    processing: dict[str, Any] | None = None,
    source_sha256: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one manifest file entry: hash + provenance for a single shipped file.

    ``processing`` labels derived media. Omit it (or pass ``None``) for a
    pristine original; pass e.g. ``{"kind": "annotated", "detail": "detection
    boxes burned in"}`` for a re-render. ``source_sha256`` references the
    original the derived file came from, when that original is also retained.
    """
    proc = dict(processing) if processing else {"kind": "original"}
    entry: dict[str, Any] = {
        "file": arcname,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "camera_id": str(camera_id) if camera_id is not None else None,
        "camera_name": camera_name,
        "recording_id": str(recording_id) if recording_id is not None else None,
        "captured_start_utc": _iso(started_at),
        "captured_end_utc": _iso(ended_at),
        "captured_start_local": _local_iso(started_at),
        "processing": proc,
        "derived": proc.get("kind", "original") != "original",
    }
    if source_sha256 is not None:
        entry["source_sha256"] = source_sha256
    if extra:
        entry["extra"] = extra
    return entry


def build_manifest(
    entries: list[dict[str, Any]],
    *,
    generated_by: str | None,
    nurby_version: str,
    build_sha: str = "",
    camera_scope: list[str] | str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the top-level manifest object over already-built file ``entries``.

    ``camera_scope`` records the caller's camera ACL at export time (a list
    of allowed camera-id strings, or ``"all"`` for an unrestricted caller),
    so a reader can see the bundle could only contain those cameras. This is
    a pure function: no DB, no disk, no clock unless ``generated_at`` is
    omitted (then it stamps ``now`` in UTC).
    """
    now = generated_at or datetime.now(timezone.utc)
    return {
        "manifest_version": MANIFEST_VERSION,
        "kind": "nurby-evidence-bundle",
        "disclaimer": _DISCLAIMER,
        "generated_at_utc": _iso(now),
        "generated_by": generated_by,
        "nurby_version": nurby_version,
        "build_sha": build_sha or None,
        "camera_scope": camera_scope,
        "hash_algorithm": "sha256",
        "file_count": len(entries),
        "files": entries,
    }
