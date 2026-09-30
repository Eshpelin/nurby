from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from services.api.routes.voiceprints import (
    MIN_VIDEO_CONFIDENCE,
    VoiceprintSampleDecision,
    _clip_response,
    _clear_voice_derived_attribution,
    _eligible_clip,
    _voiceprint_audit_record,
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


def test_voiceprint_revocation_clears_only_voice_derived_history():
    transcript = _transcript(
        speaker_source="fused",
        speaker_confidence=0.91,
    )
    old_value = _clear_voice_derived_attribution(transcript)

    assert old_value.endswith(":fused:0.91")
    assert transcript.speaker_person_id is None
    assert transcript.speaker_confidence is None
    assert transcript.speaker_source == "ambiguous"


@pytest.mark.parametrize("source", ["video", "manual", "ambiguous", None])
def test_voiceprint_revocation_preserves_non_voice_history(source):
    transcript = _transcript(speaker_source=source, speaker_confidence=0.88)
    person_id = transcript.speaker_person_id

    assert _clear_voice_derived_attribution(transcript) is None
    assert transcript.speaker_person_id == person_id
    assert transcript.speaker_confidence == 0.88
    assert transcript.speaker_source == source


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


def test_voiceprint_audit_record_contains_only_lifecycle_metadata():
    transcript = _transcript()
    transcript.id = uuid4()
    transcript.camera_id = uuid4()
    user = SimpleNamespace(id=uuid4())

    audit = _voiceprint_audit_record(
        transcript,
        user,
        field="voiceprint_revoked",
        old_value="confirmed:consented",
        new_value="removed:not_consented",
    )

    assert audit.transcript_id == transcript.id
    assert audit.camera_id == transcript.camera_id
    assert audit.user_id == user.id
    assert audit.field == "voiceprint_revoked"
    assert audit.old_value == "confirmed:consented"
    assert audit.new_value == "removed:not_consented"
    assert not hasattr(audit, "embedding")
