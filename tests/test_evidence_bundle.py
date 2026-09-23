"""Evidence-bundle export (issue #225).

Two layers, matching the DB-free convention of this suite:

* **Pure manifest generation** — ``sha256_file`` hashes the shipped bytes,
  ``manifest_entry``/``build_manifest`` assemble hashes + provenance, and
  derived media is labeled. No DB, no app.
* **Endpoint camera-scope enforcement** — the export handler runs against a
  stubbed AsyncSession. The recordings query must carry the caller's ACL
  (the granted camera in the WHERE clause, the foreign one never), and the
  produced zip's manifest must contain only the in-scope file, with a
  SHA-256 that matches the bytes on disk.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
import zipfile
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services.api import evidence_bundle as eb
from services.api.routes import recordings as recordings_routes

T0 = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 9, 17, 12, 5, tzinfo=timezone.utc)

CAM_A = uuid.uuid4()  # the selected user's only granted camera
CAM_B = uuid.uuid4()  # a foreign camera that must never appear in a bundle


# ── pure manifest generation ─────────────────────────────────────────

def test_sha256_file_matches_hashlib(tmp_path):
    p = tmp_path / "clip.mp4"
    data = b"the exact bytes shipped" * 1000
    p.write_bytes(data)
    assert eb.sha256_file(str(p)) == hashlib.sha256(data).hexdigest()


def test_manifest_entry_carries_hash_and_provenance():
    entry = eb.manifest_entry(
        arcname="20260917-120000-clip.mp4",
        sha256="abc123",
        size_bytes=42,
        camera_id=CAM_A,
        camera_name="Front Door",
        recording_id="rec-1",
        started_at=T0,
        ended_at=T1,
    )
    assert entry["file"] == "20260917-120000-clip.mp4"
    assert entry["sha256"] == "abc123"
    assert entry["size_bytes"] == 42
    assert entry["camera_id"] == str(CAM_A)
    assert entry["camera_name"] == "Front Door"
    assert entry["recording_id"] == "rec-1"
    assert entry["captured_start_utc"] == "2026-09-17T12:00:00Z"
    assert entry["captured_end_utc"] == "2026-09-17T12:05:00Z"
    # A plain original is labeled as such and not flagged derived.
    assert entry["processing"] == {"kind": "original"}
    assert entry["derived"] is False


def test_manifest_entry_labels_derived_media():
    entry = eb.manifest_entry(
        arcname="clip-annotated.mp4",
        sha256="def456",
        size_bytes=10,
        camera_id=CAM_A,
        camera_name="Front Door",
        recording_id="rec-1",
        started_at=T0,
        ended_at=T1,
        processing={"kind": "annotated", "detail": "detection boxes burned in"},
        source_sha256="orig-hash",
    )
    assert entry["derived"] is True
    assert entry["processing"]["kind"] == "annotated"
    # The retained original is referenced by hash so nothing masquerades as
    # untouched source footage.
    assert entry["source_sha256"] == "orig-hash"


def test_build_manifest_shape_and_disclaimer():
    entries = [
        eb.manifest_entry(
            arcname="a.mp4", sha256="h1", size_bytes=3, camera_id=CAM_A,
            camera_name="A", recording_id="r1", started_at=T0, ended_at=T1,
        ),
    ]
    manifest = eb.build_manifest(
        entries,
        generated_by="op@example.com",
        nurby_version="1.2.3",
        build_sha="deadbeef",
        camera_scope=[str(CAM_A)],
        generated_at=T0,
    )
    assert manifest["kind"] == "nurby-evidence-bundle"
    assert manifest["hash_algorithm"] == "sha256"
    assert manifest["file_count"] == 1
    assert manifest["files"][0]["sha256"] == "h1"
    assert manifest["generated_by"] == "op@example.com"
    assert manifest["nurby_version"] == "1.2.3"
    assert manifest["build_sha"] == "deadbeef"
    assert manifest["camera_scope"] == [str(CAM_A)]
    assert manifest["generated_at_utc"] == "2026-09-17T12:00:00Z"
    # The bundle must not over-claim: the caveat travels inside the manifest.
    assert "chain of custody" in manifest["disclaimer"].lower()


# ── endpoint camera-scope enforcement ────────────────────────────────

class _Result:
    def __init__(self, *, scalars=None, rows=None):
        self._scalars = list(scalars or [])
        self._rows = list(rows or [])

    def scalars(self):
        m = MagicMock()
        m.all.return_value = self._scalars
        m.first.return_value = self._scalars[0] if self._scalars else None
        return m

    def all(self):
        return self._rows


class _StubDB:
    """AsyncSession stand-in dispatching on the compiled table name.

    ``grants`` seeds the ``user_camera_access`` rows read by
    ``allowed_camera_ids``; ``recordings`` are the rows a scope-honoring DB
    would return (already filtered to the grant); ``cameras`` back the name
    lookup. Every executed statement is captured so the test can compile the
    recordings query and assert the ACL was pushed into the WHERE clause.
    """

    def __init__(self, *, grants, recordings, cameras):
        self.grants = list(grants)
        self._recordings = list(recordings)
        self._cameras = list(cameras)
        self.executed: list = []

    async def execute(self, stmt):
        self.executed.append(stmt)
        sql = str(stmt).lower()
        if "user_camera_access" in sql:
            return _Result(rows=[(g,) for g in self.grants])
        if "from cameras" in sql:
            return _Result(rows=self._cameras)
        if "from recordings" in sql:
            return _Result(scalars=self._recordings)
        return _Result()

    async def get(self, model, ident):
        if model.__name__ == "User":
            return SimpleNamespace(
                id=ident, role="user", camera_access_mode="selected",
                is_active=True, email="op@example.com",
            )
        return None


def _recording(cam_id, path):
    return SimpleNamespace(
        id=uuid.uuid4(), camera_id=cam_id, file_path=path,
        started_at=T0, ended_at=T1, duration_seconds=300.0,
        thumbnail_path=None,
    )


def test_evidence_bundle_scopes_to_allowed_cameras(tmp_path, monkeypatch):
    # Only the granted camera's recording exists on disk / in the result set.
    mine = tmp_path / "mine.mp4"
    mine.write_bytes(b"granted-camera-bytes")
    rec = _recording(CAM_A, "mine.mp4")

    monkeypatch.setattr(recordings_routes.settings, "recordings_path", str(tmp_path))
    user_id = uuid.uuid4()
    monkeypatch.setattr(recordings_routes, "require_query_token", lambda token: user_id)

    db = _StubDB(
        grants=[CAM_A],
        recordings=[rec],
        cameras=[(CAM_A, "Front Door")],
    )

    resp = asyncio.run(
        recordings_routes.download_evidence_bundle(
            token="t", recording_id=[], camera_id=None, from_=None, to=None,
            object=[], person_id=None, vehicle_id=None, db=db,
        )
    )

    # The recordings query must carry the ACL: CAM_A in, CAM_B never.
    rec_stmts = [s for s in db.executed if "from recordings" in str(s).lower()]
    assert rec_stmts, "recordings query was not issued"
    compiled = str(
        rec_stmts[-1].compile(compile_kwargs={"literal_binds": True})
    ).replace("-", "").lower()
    assert CAM_A.hex in compiled
    assert CAM_B.hex not in compiled

    # The produced zip carries the media plus a manifest whose hash matches
    # the shipped bytes, and only the in-scope camera appears.
    with zipfile.ZipFile(resp.path) as zf:
        names = zf.namelist()
        assert eb.MANIFEST_FILENAME in names
        manifest = json.loads(zf.read(eb.MANIFEST_FILENAME))
        assert manifest["file_count"] == 1
        f = manifest["files"][0]
        assert f["camera_id"] == str(CAM_A)
        assert f["camera_name"] == "Front Door"
        assert f["sha256"] == hashlib.sha256(mine.read_bytes()).hexdigest()
        # The hash in the manifest verifies the exact bytes in the archive.
        assert zf.read(f["file"]) == mine.read_bytes()
        assert str(CAM_B) not in json.dumps(manifest)
        assert manifest["camera_scope"] == [str(CAM_A)]


def test_evidence_bundle_404_when_no_recordings(tmp_path, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(recordings_routes.settings, "recordings_path", str(tmp_path))
    user_id = uuid.uuid4()
    monkeypatch.setattr(recordings_routes, "require_query_token", lambda token: user_id)
    db = _StubDB(grants=[CAM_A], recordings=[], cameras=[])
    with pytest.raises(HTTPException) as ei:
        asyncio.run(
            recordings_routes.download_evidence_bundle(
                token="t", recording_id=[], camera_id=None, from_=None, to=None,
                object=[], person_id=None, vehicle_id=None, db=db,
            )
        )
    assert ei.value.status_code == 404
