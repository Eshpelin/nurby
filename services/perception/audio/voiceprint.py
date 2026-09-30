"""Consent-gated local voiceprint training (#272).

This is deliberately a small, offline baseline rather than a claim of
state-of-the-art diarization.  It derives a normalized MFCC/delta profile
from clips explicitly confirmed in the voiceprint review UI.  The model
version is persisted so a stronger local speaker model can replace it without
silently comparing incompatible vectors.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from uuid import UUID

import numpy as np
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import settings
from shared.app_settings import get_setting
from shared.models import AudioCapture, Camera, Person, Transcript, VoiceprintProfile, VoiceprintSampleReview
from shared.paths import resolve_inside

logger = logging.getLogger("nurby.perception.audio.voiceprint")

MODEL_VERSION = "mfcc-local-v1"
EMBEDDING_DIMENSION = 240
MATCH_THRESHOLD = 0.88
MATCH_MARGIN = 0.05


def extract_voiceprint_features(path: str) -> list[float]:
    """Extract one bounded, normalized local feature vector from an audio file."""
    import librosa

    samples, _ = librosa.load(path, sr=16_000, mono=True)
    if samples.size < 16_000:
        raise ValueError("audio clip is shorter than one second")
    mfcc = librosa.feature.mfcc(y=samples, sr=16_000, n_mfcc=40)
    delta = librosa.feature.delta(mfcc)
    delta2 = librosa.feature.delta(mfcc, order=2)
    vector = np.concatenate(
        (
            mfcc.mean(axis=1), mfcc.std(axis=1),
            delta.mean(axis=1), delta.std(axis=1),
            delta2.mean(axis=1), delta2.std(axis=1),
        )
    )
    if vector.size != EMBEDDING_DIMENSION or not np.isfinite(vector).all():
        raise ValueError("audio feature extraction returned an invalid vector")
    norm = float(np.linalg.norm(vector))
    if norm <= 0:
        raise ValueError("audio feature extraction returned an empty vector")
    return (vector / norm).astype(np.float32).tolist()


def select_voiceprint_match(
    candidates: list[tuple[UUID, list[float]]],
    vector: list[float],
    *,
    threshold: float = MATCH_THRESHOLD,
    margin: float = MATCH_MARGIN,
) -> tuple[UUID, float] | None:
    """Choose one sufficiently separated profile, otherwise remain unknown."""
    probe = np.asarray(vector, dtype=np.float32)
    probe_norm = float(np.linalg.norm(probe))
    if probe_norm <= 0:
        return None
    scored: list[tuple[UUID, float]] = []
    for person_id, embedding in candidates:
        profile = np.asarray(embedding, dtype=np.float32)
        profile_norm = float(np.linalg.norm(profile))
        if profile_norm <= 0 or profile.shape != probe.shape:
            continue
        score = float(np.dot(probe, profile) / (probe_norm * profile_norm))
        if np.isfinite(score):
            scored.append((person_id, score))
    if not scored:
        return None
    scored.sort(key=lambda item: item[1], reverse=True)
    best = scored[0]
    if best[1] < threshold or len(scored) > 1 and best[1] - scored[1][1] < margin:
        return None
    return best


async def match_voiceprint(
    db: AsyncSession,
    capture: AudioCapture,
    *,
    person_id: UUID | None = None,
) -> tuple[UUID, float] | None:
    """Return a conservative hypothesis for one retained capture."""
    # Enrollment consent is person-specific; inference also requires the
    # administrator's explicit deployment-level opt-in. This keeps a newly
    # migrated or restored profile from silently activating matching.
    if not bool(await get_setting("voiceprint_matching_enabled", False)):
        return None
    path = resolve_inside(capture.file_path, settings.audio_storage_path)
    if not path or not os.path.exists(path):
        return None
    try:
        vector = extract_voiceprint_features(path)
    except Exception:
        logger.warning("voiceprint matching failed capture=%s", capture.id, exc_info=True)
        return None
    profile_query = (
        select(VoiceprintProfile.person_id, VoiceprintProfile.embedding)
        .join(Person, Person.id == VoiceprintProfile.person_id)
        .join(Camera, Camera.id == capture.camera_id)
        .where(VoiceprintProfile.status == "ready")
        .where(VoiceprintProfile.consent_confirmed.is_(True))
        .where(VoiceprintProfile.model_version == MODEL_VERSION)
        .where(VoiceprintProfile.embedding.is_not(None))
        # A facility-scoped camera may only use profiles belonging to the
        # same facility, while unscoped people/cameras retain the legacy
        # household-wide behavior. This prevents a profile from one
        # facility being used to label speech captured in another.
        .where(
            or_(
                Camera.facility_id.is_(None),
                Person.facility_id.is_(None),
                Person.facility_id == Camera.facility_id,
            )
        )
    )
    if person_id is not None:
        profile_query = profile_query.where(VoiceprintProfile.person_id == person_id)
    rows = (await db.execute(profile_query)).all()
    return select_voiceprint_match([(profile_person_id, embedding) for profile_person_id, embedding in rows], vector)


async def train_voiceprint(db: AsyncSession, person_id: UUID) -> VoiceprintProfile:
    """Rebuild a person's profile only from confirmed, consented clips.

    Missing/expired audio is skipped and reported in ``last_error``.  The
    vector itself stays database-internal and is never returned by the API.
    """
    if await db.get(Person, person_id) is None:
        raise ValueError("person not found")
    profile = await db.scalar(select(VoiceprintProfile).where(VoiceprintProfile.person_id == person_id))
    if profile is None:
        profile = VoiceprintProfile(person_id=person_id, model_version=MODEL_VERSION)
        db.add(profile)
        await db.flush()

    rows = (await db.execute(
        select(Transcript, AudioCapture)
        .join(VoiceprintSampleReview, VoiceprintSampleReview.transcript_id == Transcript.id)
        .join(AudioCapture, AudioCapture.id == Transcript.audio_capture_id)
        .where(VoiceprintSampleReview.person_id == person_id)
        .where(VoiceprintSampleReview.decision == "confirmed")
        .where(VoiceprintSampleReview.consent_given.is_(True))
        .order_by(Transcript.started_at.asc())
    )).all()

    vectors: list[np.ndarray] = []
    source_ids: list[str] = []
    skipped = 0
    for transcript, capture in rows:
        path = resolve_inside(capture.file_path, settings.audio_storage_path)
        if not path or not os.path.exists(path):
            skipped += 1
            continue
        try:
            vectors.append(np.asarray(extract_voiceprint_features(path), dtype=np.float32))
            source_ids.append(str(transcript.id))
        except Exception:
            skipped += 1
            logger.warning("voiceprint feature extraction failed transcript=%s", transcript.id, exc_info=True)

    now = datetime.now(timezone.utc)
    profile.model_version = MODEL_VERSION
    profile.source_transcript_ids = source_ids
    profile.sample_count = len(source_ids)
    profile.consent_confirmed = bool(source_ids)
    profile.trained_at = now if source_ids else None
    profile.last_error = f"{skipped} confirmed clip(s) unavailable or could not be decoded." if skipped else None
    if not vectors:
        profile.embedding = None
        profile.status = "not_ready"
        if not profile.last_error:
            profile.last_error = "No retained confirmed audio clips are available."
        return profile

    mean = np.mean(vectors, axis=0)
    norm = float(np.linalg.norm(mean))
    if norm <= 0 or not np.isfinite(mean).all():
        profile.embedding = None
        profile.status = "failed"
        profile.last_error = "The confirmed clips did not produce a valid voiceprint."
        return profile
    profile.embedding = (mean / norm).astype(np.float32).tolist()
    profile.status = "ready"
    return profile
