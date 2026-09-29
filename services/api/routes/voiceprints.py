"""Existing-audio voiceprint enrollment review (#272).

Candidates are limited to transcript segments attributed through video
evidence. This route records explicit clip decisions and consent; it does not
pretend to create a biometric model before an enrollment worker exists.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.perception.audio.voiceprint import train_voiceprint
from shared.auth import require_admin
from shared.camera_access import ALL, allowed_camera_ids
from shared.config import settings
from shared.database import get_db
from shared.models import AudioCapture, Camera, Person, Transcript, User, VoiceprintProfile, VoiceprintSampleReview
from shared.paths import resolve_inside

router = APIRouter()
MIN_CLIP_SECONDS = 2.0
MIN_VIDEO_CONFIDENCE = 0.75


class VoiceprintSampleDecision(BaseModel):
    transcript_id: uuid.UUID
    decision: Literal["confirm", "reject", "reopen", "remove"]
    consent_given: bool = False


def _eligible_clip(transcript: Transcript) -> bool:
    return (
        not transcript.filtered
        and transcript.audio_capture_id is not None
        and transcript.speaker_person_id is not None
        and transcript.speaker_source == "video"
        and float(transcript.speaker_confidence or 0.0) >= MIN_VIDEO_CONFIDENCE
        and (transcript.ended_at - transcript.started_at).total_seconds() >= MIN_CLIP_SECONDS
    )


def _clip_response(
    transcript: Transcript,
    capture: AudioCapture | None,
    camera: Camera | None,
    review: VoiceprintSampleReview | None,
) -> dict:
    duration = (transcript.ended_at - transcript.started_at).total_seconds()
    audio_available = bool(
        capture
        and resolve_inside(capture.file_path, settings.audio_storage_path)
        and os.path.exists(resolve_inside(capture.file_path, settings.audio_storage_path))
    )
    quality_reasons = []
    if duration < MIN_CLIP_SECONDS:
        quality_reasons.append("too_short")
    if not audio_available:
        quality_reasons.append("audio_not_retained")
    if float(transcript.speaker_confidence or 0.0) < MIN_VIDEO_CONFIDENCE:
        quality_reasons.append("weak_visual_attribution")
    if transcript.filtered:
        quality_reasons.append("filtered_transcript")
    return {
        "transcript_id": str(transcript.id),
        "audio_capture_id": str(capture.id) if capture else None,
        "audio_url": f"/api/audio/{capture.id}" if capture else None,
        "camera_id": str(transcript.camera_id),
        "camera_name": camera.name if camera else None,
        "started_at": transcript.started_at,
        "ended_at": transcript.ended_at,
        "duration_seconds": round(duration, 3),
        "transcript": transcript.text,
        "speaker_confidence": transcript.speaker_confidence,
        "attribution_reason": "A single person was attributed by camera presence for this speech segment.",
        "other_speakers_present": None,
        "audio_available": audio_available,
        "review_status": review.decision if review else "candidate",
        "consent_given": bool(review and review.consent_given),
        "reviewed_at": review.reviewed_at if review else None,
        "quality": {
            "eligible": not quality_reasons,
            "duration_ok": duration >= MIN_CLIP_SECONDS,
            "audio_retained": audio_available,
            "visual_attribution_ok": float(transcript.speaker_confidence or 0.0) >= MIN_VIDEO_CONFIDENCE,
            "reasons": quality_reasons,
        },
        "attribution_model_version": "video-correlated-v1",
    }


@router.get("/persons/{person_id}/candidates")
async def list_voiceprint_candidates(
    person_id: uuid.UUID,
    include_rejected: bool = Query(default=False),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if await db.get(Person, person_id) is None:
        raise HTTPException(status_code=404, detail="Person not found")
    allowed = await allowed_camera_ids(current_user, db)
    query = (
        select(Transcript, AudioCapture, Camera, VoiceprintSampleReview)
        .join(AudioCapture, AudioCapture.id == Transcript.audio_capture_id)
        .outerjoin(Camera, Camera.id == Transcript.camera_id)
        .outerjoin(
            VoiceprintSampleReview,
            and_(
                VoiceprintSampleReview.transcript_id == Transcript.id,
                VoiceprintSampleReview.person_id == person_id,
            ),
        )
        .where(Transcript.speaker_person_id == person_id)
        .where(Transcript.speaker_source == "video")
        .where(Transcript.filtered.is_(False))
        .where(Transcript.speaker_confidence >= MIN_VIDEO_CONFIDENCE)
        .order_by(Transcript.started_at.desc())
        .limit(200)
    )
    if allowed is not ALL:
        query = query.where(Transcript.camera_id.in_(allowed))
    rows = (await db.execute(query)).all()
    candidates = []
    for transcript, capture, camera, review in rows:
        if not _eligible_clip(transcript):
            continue
        if review and review.decision in {"rejected", "removed"} and not include_rejected:
            continue
        candidates.append(_clip_response(transcript, capture, camera, review))
    profile = await db.scalar(select(VoiceprintProfile).where(VoiceprintProfile.person_id == person_id))
    return {
        "person_id": str(person_id),
        "requires_manual_sample": False,
        "consent_required_before_training": True,
        "training_available": True,
        "training_ready": bool(profile and profile.status == "ready"),
        "training_status": profile.status if profile else "not_ready",
        "training_sample_count": profile.sample_count if profile else 0,
        "training_model_version": profile.model_version if profile else None,
        "training_at": profile.trained_at if profile else None,
        "training_message": (
            "Voiceprint ready from confirmed clips; matching remains a hypothesis."
            if profile and profile.status == "ready"
            else "Confirm eligible clips and biometric consent to build a local voiceprint."
        ),
        "candidates": candidates,
    }


@router.post("/persons/{person_id}/candidates/decision")
async def decide_voiceprint_candidate(
    person_id: uuid.UUID,
    body: VoiceprintSampleDecision,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    if await db.get(Person, person_id) is None:
        raise HTTPException(status_code=404, detail="Person not found")
    transcript = await db.get(Transcript, body.transcript_id)
    if transcript is None or transcript.speaker_person_id != person_id or not _eligible_clip(transcript):
        raise HTTPException(status_code=404, detail="Eligible voiceprint clip not found")
    allowed = await allowed_camera_ids(current_user, db)
    if allowed is not ALL and transcript.camera_id not in allowed:
        raise HTTPException(status_code=404, detail="Eligible voiceprint clip not found")
    if body.decision == "confirm" and not body.consent_given:
        raise HTTPException(status_code=422, detail="Explicit biometric consent is required to confirm a clip")
    review = (
        await db.execute(
            select(VoiceprintSampleReview)
            .where(VoiceprintSampleReview.person_id == person_id)
            .where(VoiceprintSampleReview.transcript_id == transcript.id)
        )
    ).scalar_one_or_none()
    if review is None:
        review = VoiceprintSampleReview(person_id=person_id, transcript_id=transcript.id)
        db.add(review)
    review.decision = {
        "confirm": "confirmed",
        "reject": "rejected",
        "reopen": "candidate",
        "remove": "removed",
    }[body.decision]
    review.consent_given = body.decision == "confirm" and body.consent_given
    review.reviewed_by_user_id = current_user.id
    review.reviewed_at = datetime.now(timezone.utc)
    profile = await train_voiceprint(db, person_id)
    await db.commit()
    return {
        "person_id": str(person_id),
        "transcript_id": str(transcript.id),
        "decision": review.decision,
        "consent_given": review.consent_given,
        "training_started": body.decision in {"confirm", "remove"},
        "training_status": profile.status,
        "training_sample_count": profile.sample_count,
        "training_model_version": profile.model_version,
        "training_message": (
            "Local voiceprint rebuilt from confirmed clips; attribution remains a hypothesis."
            if profile.status == "ready"
            else profile.last_error or "No retained confirmed audio clips are available yet."
        ),
    }


@router.delete("/persons/{person_id}/profile")
async def revoke_voiceprint_profile(
    person_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete the derived profile and revoke every confirmed source clip."""
    if await db.get(Person, person_id) is None:
        raise HTTPException(status_code=404, detail="Person not found")
    profile = await db.scalar(select(VoiceprintProfile).where(VoiceprintProfile.person_id == person_id))
    reviews = (await db.execute(
        select(VoiceprintSampleReview)
        .where(VoiceprintSampleReview.person_id == person_id)
        .where(VoiceprintSampleReview.decision == "confirmed")
    )).scalars().all()
    now = datetime.now(timezone.utc)
    for review in reviews:
        review.decision = "removed"
        review.consent_given = False
        review.reviewed_by_user_id = current_user.id
        review.reviewed_at = now
    if profile is not None:
        await db.delete(profile)
    await db.commit()
    return {
        "person_id": str(person_id),
        "profile_deleted": profile is not None,
        "clips_revoked": len(reviews),
        "training_ready": False,
    }
