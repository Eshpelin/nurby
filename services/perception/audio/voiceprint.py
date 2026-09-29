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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import settings
from shared.models import AudioCapture, Person, Transcript, VoiceprintProfile, VoiceprintSampleReview
from shared.paths import resolve_inside

logger = logging.getLogger("nurby.perception.audio.voiceprint")

MODEL_VERSION = "mfcc-local-v1"
EMBEDDING_DIMENSION = 240


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
