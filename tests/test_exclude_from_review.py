"""Per-camera ``exclude_from_review`` flag (issue #38).

A camera with ``exclude_from_review=True`` is dropped from the review /
alerts / timeline feed and their filters, but keeps recording and stays a
valid recording target. Distinct from the dashboard camera-wall hide.

The suite has no live DB, so feed queries are validated by compiling them
for the Postgres dialect (catches construction bugs) and by asserting on
the model / schema surface. Semantic behaviour against real rows is covered
by the manual end-to-end check.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import and_, select
from sqlalchemy.dialects import postgresql

from services.api.routes import events as ev
from shared.models import Camera, Event, Observation, Transcript
from shared.schemas import CameraCreate, CameraResponse, CameraUpdate


def _sql(query) -> str:
    return str(
        query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    ).lower()


# ── model + schema surface ──────────────────────────────────────────────

def test_model_has_column_default_false():
    col = Camera.__table__.columns["exclude_from_review"]
    assert col.nullable is False
    # server_default renders the SQL false literal
    assert "false" in str(col.server_default.arg).lower()


def test_create_schema_defaults_false():
    c = CameraCreate(name="cam", stream_url="rtsp://host/s")
    assert c.exclude_from_review is False
    # explicit true round-trips
    c2 = CameraCreate(name="cam", stream_url="rtsp://host/s", exclude_from_review=True)
    assert c2.exclude_from_review is True


def test_update_schema_is_optional_tristate():
    # unset stays out of model_dump(exclude_unset=True) -> PATCH passthrough
    u = CameraUpdate()
    assert "exclude_from_review" not in u.model_dump(exclude_unset=True)
    u2 = CameraUpdate(exclude_from_review=True)
    dumped = u2.model_dump(exclude_unset=True)
    assert dumped["exclude_from_review"] is True


def test_response_schema_exposes_flag():
    assert "exclude_from_review" in CameraResponse.model_fields


# ── recording target stays valid (flag is review-only) ──────────────────

def test_excluded_camera_still_records():
    # The flag must not touch recording config. A camera can be hidden from
    # review while still recording.
    c = CameraCreate(
        name="noisy", stream_url="rtsp://host/s",
        exclude_from_review=True, recording_mode="always", recording_enabled=True,
    )
    assert c.exclude_from_review is True
    assert c.recording_mode == "always"
    assert c.recording_enabled is True


# ── alerts feed (events) honors the flag ────────────────────────────────

def test_list_events_query_excludes_flagged_cameras():
    # Mirror the construction in routes.events.list_events.
    q = select(Event).where(ev._not_review_excluded(Event.camera_id))
    sql = _sql(q)
    assert "exclude_from_review" in sql
    # null camera_id rows are kept (no source camera)
    assert "camera_id is null" in sql


@pytest.mark.asyncio
async def test_filtered_events_query_excludes_flagged_cameras():
    # person_id None -> the helper never touches the db, so a dummy is fine.
    q = await ev._filtered_events_query(db=None)
    sql = _sql(q)
    assert "exclude_from_review" in sql


# ── review list (observations) honors the flag ──────────────────────────

def test_observations_query_excludes_flagged_cameras():
    # Mirror the construction in routes.observations.list_observations.
    q = select(Observation).where(
        Observation.camera_id.not_in(
            select(Camera.id).where(Camera.exclude_from_review.is_(True))
        )
    )
    sql = _sql(q)
    assert "exclude_from_review" in sql
    assert "not in" in sql


# ── timeline feed honors the flag for both observations and transcripts ──

def test_timeline_query_excludes_flagged_cameras_both_kinds():
    # Mirror the construction in routes.timeline.get_timeline.
    excluded = select(Camera.id).where(Camera.exclude_from_review.is_(True))
    obs_q = select(Observation).where(
        and_(Observation.camera_id.not_in(excluded))
    )
    tx_q = select(Transcript).where(
        and_(
            Transcript.filtered.is_(False),
            Transcript.camera_id.not_in(excluded),
        )
    )
    obs_sql = _sql(obs_q)
    tx_sql = _sql(tx_q)
    assert "exclude_from_review" in obs_sql
    assert "exclude_from_review" in tx_sql


# ── filter does not break the still-present camera filter ────────────────

def test_camera_filter_and_review_exclusion_compose():
    cam = uuid.uuid4()
    excluded = select(Camera.id).where(Camera.exclude_from_review.is_(True))
    obs_q = select(Observation).where(
        and_(
            Observation.camera_id.not_in(excluded),
            Observation.camera_id == cam,
            Observation.started_at >= datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
    )
    sql = _sql(obs_q)
    assert "exclude_from_review" in sql
    assert "camera_id =" in sql
    assert "started_at >=" in sql
