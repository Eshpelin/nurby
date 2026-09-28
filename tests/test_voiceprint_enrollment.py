from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from services.api.routes.voiceprints import (
    MIN_VIDEO_CONFIDENCE,
    VoiceprintSampleDecision,
    _clip_response,
    _eligible_clip,
)


def _transcript(**overrides):
    start = datetime(2026, 9, 27, 10, tzinfo=timezone.utc)
    values = {
        "filtered": False,
        "audio_capture_id": uuid4(),
        "speaker_person_id": uuid4(),
        "speaker_source": "video",
        "speaker_confidence": MIN_VIDEO_CONFIDENCE,
        "started_at": start,
        "ended_at": start + timedelta(seconds=3),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_candidate_requires_strong_video_attribution_and_audio_duration():
    assert _eligible_clip(_transcript())
    assert not _eligible_clip(_transcript(speaker_source="voice"))
    assert not _eligible_clip(_transcript(speaker_confidence=0.74))
    assert not _eligible_clip(_transcript(ended_at=_transcript().started_at + timedelta(seconds=1)))
    assert not _eligible_clip(_transcript(audio_capture_id=None))


def test_biometric_confirmation_requires_explicit_consent_payload():
    body = VoiceprintSampleDecision(
        transcript_id=uuid4(), decision="confirm", consent_given=True
    )
    assert body.consent_given is True
    assert VoiceprintSampleDecision(transcript_id=uuid4(), decision="reject").consent_given is False


def test_voiceprint_sample_review_keeps_consent_separate_from_attribution():
    from shared.models import VoiceprintSampleReview

    review = VoiceprintSampleReview(
        person_id=uuid4(), transcript_id=uuid4(), decision="confirmed", consent_given=True
    )
    assert review.decision == "confirmed"
    assert review.consent_given is True


def test_candidate_response_exposes_quality_without_biometric_artifacts():
    transcript = _transcript()
    transcript.id = uuid4()
    transcript.camera_id = uuid4()
    transcript.text = "hello"
    capture = SimpleNamespace(id=uuid4(), file_path="missing.wav")
    camera = SimpleNamespace(name="Front door")
    response = _clip_response(transcript, capture, camera, None)

    assert response["quality"] == {
        "eligible": False,
        "duration_ok": True,
        "audio_retained": False,
        "visual_attribution_ok": True,
        "reasons": ["audio_not_retained"],
    }
    assert response["attribution_model_version"] == "video-correlated-v1"
    assert "voiceprint" not in response
    assert "embedding" not in response
