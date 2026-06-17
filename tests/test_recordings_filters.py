"""Recordings review filters: the camera/time/object query construction and
the bundle zip helper. The suite has no live DB, so the SQL is validated by
compiling it for the Postgres dialect (catches construction bugs); semantic
behaviour against real rows is covered by the manual end-to-end check."""

import uuid
import zipfile
from datetime import datetime, timezone

from sqlalchemy.dialects import postgresql

from services.api.routes.recordings import _build_zip, _filtered_recordings_query


def _sql(query) -> str:
    return str(
        query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    ).lower()


def test_camera_and_time_filters_present():
    cid = uuid.uuid4()
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 6, 2, tzinfo=timezone.utc)
    sql = _sql(_filtered_recordings_query(cid, t0, t1, None))
    assert "from recordings" in sql
    assert "camera_id =" in sql
    # Lower bound tests the recording's window_end (overlap semantics, #65),
    # not started_at, so a clip that began before `from_` but is still
    # running is not dropped. window_end is coalesce(ended_at, started_at +
    # make_interval(duration)).
    assert "make_interval" in sql
    assert ">=" in sql
    assert "started_at <=" in sql  # upper bound stays on started_at
    assert "exists" not in sql  # no object filter -> no subquery


def test_object_filter_adds_label_exists_subquery():
    sql = _sql(_filtered_recordings_query(None, None, None, "cat"))
    assert "exists" in sql
    assert "ilike" in sql
    assert 'label": "cat' in sql            # the JSON label match pattern
    assert "make_interval" in sql           # window upper bound when ended_at is null


def test_no_filters_is_bare_select():
    sql = _sql(_filtered_recordings_query(None, None, None, None))
    assert "from recordings" in sql
    assert "where" not in sql


def test_object_filter_escapes_like_wildcards():
    # A label with a LIKE metachar must be escaped, not treated as a wildcard.
    sql = _sql(_filtered_recordings_query(None, None, None, "ca%t"))
    assert "escape" in sql  # ilike(..., escape="\\") rendered


def test_build_zip_stored_and_complete(tmp_path):
    a = tmp_path / "a.mp4"
    a.write_bytes(b"aaa")
    b = tmp_path / "b.mp4"
    b.write_bytes(b"bbbb")
    out = tmp_path / "bundle.zip"
    _build_zip([("20260601-000000-a.mp4", str(a)), ("20260601-000100-b.mp4", str(b))], str(out))

    with zipfile.ZipFile(out) as zf:
        assert zf.namelist() == ["20260601-000000-a.mp4", "20260601-000100-b.mp4"]
        for info in zf.infolist():
            assert info.compress_type == zipfile.ZIP_STORED  # mp4 already compressed
        assert zf.read("20260601-000000-a.mp4") == b"aaa"
        assert zf.read("20260601-000100-b.mp4") == b"bbbb"
