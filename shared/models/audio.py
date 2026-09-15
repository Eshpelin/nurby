"""Sound: captures, transcripts, detections, the audit trail over all of
it, and the two-way voice conversations held through a camera.

Split out of the single ``models.py``; import from ``shared.models``,
which still re-exports every model in this package.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.database import Base


class AudioCapture(Base):
    __tablename__ = "audio_captures"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    codec: Mapped[str] = mapped_column(String(16), default="opus", nullable=False)
    sample_rate: Mapped[int] = mapped_column(Integer, default=16000, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    audio_capture_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audio_captures.id", ondelete="SET NULL"), nullable=True, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    original_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_speech_prob: Mapped[float | None] = mapped_column(Float, nullable=True)
    words: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    filtered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    speaker_person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id", ondelete="SET NULL"), nullable=True
    )
    speaker_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    speaker_source: Mapped[str | None] = mapped_column(String(16), nullable=True)  # video, voice, fused, ambiguous
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AudioAuditLog(Base):
    __tablename__ = "audio_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    new_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AudioDetection(Base):
    __tablename__ = "audio_detections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Normalized class name. baby_cry, scream, speech, glass_break, alarm, bark, gunshot
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    # Raw AudioSet class (useful for debugging / future remapping)
    raw_class: Mapped[str | None] = mapped_column(String(128), nullable=True)


class SpeechEvent(Base):
    """Every utterance a camera was asked to make, played or not (#155).

    Written for suppressed attempts as well as successful ones. A
    household must be able to read back both what their house said and
    what it decided not to say, and the second is often the more
    interesting audit: a rule that has been silently suppressed by quiet
    hours for a month looks identical to one that never fired, unless the
    suppression is recorded.

    ``text`` is the rendered utterance, not the template, because the
    template is safe and the render is what was actually spoken.
    """

    __tablename__ = "speech_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rules.id", ondelete="SET NULL"), nullable=True
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )
    # Which spoken exchange this line belonged to, when it belonged to
    # one. Without it a transcript would have to be reassembled from
    # camera plus time window, which silently interleaves two sessions
    # that happen back to back at the same door.
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("voice_sessions.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    # Which agent run decided to say this. The Ask agent carries the
    # household orientation block, so an utterance it initiated is the
    # one most worth being able to trace back to a question.
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # rule | agent | manual | conversation
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, default="rule")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    voice: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transport: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # queued | played | failed | suppressed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    # quiet_hours | cooldown | daily_cap | policy | estop | disabled |
    # unsupported | empty_text | volume
    suppressed_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    played_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VoiceSession(Base):
    """One spoken exchange at a camera (issue #157).

    A session is opened when someone speaks near a camera whose policy
    allows conversation, and closed by a hard stop: the visitor leaves,
    the turn or time budget runs out, or a person takes over.

    ``handed_off_to_user_id`` is the outcome to design for rather than
    the exception. The agent's job is to hold the line politely for a few
    seconds while a push reaches the household, not to represent them; a
    session that ends in a handoff is the feature working, not failing.
    """

    __tablename__ = "voice_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Links the spoken exchange to the transcript rows it came from, so
    # the timeline can show both halves of the conversation together.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # visitor_silent | max_turns | max_seconds | handed_off | policy |
    # error | camera_disabled
    ended_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    turns: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    handed_off_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    handed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Every refusal the disclosure filter made this session. Kept so a
    # household can see what their camera declined to say, which is the
    # audit that matters most for a talking agent.
    refusals: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Conversation(Base):
    """A rolling group of consecutive transcripts on a camera.

    Boundary is a gap heuristic. transcripts whose start is within
    ``conversation_gap_seconds`` of the previous transcript's end on
    the same camera belong to the same conversation. The conversation
    is marked ``finalized`` and summarized after the gap window passes
    with no new transcript.
    """

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Advances every time a transcript is appended.
    ended_at_provisional: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set when the conversation closes.
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transcript_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    finalized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_provider_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cleaned_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    speakers_seen: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    clip_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    clip_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Native-audio analysis (docs/native-audio-conversation-design.md).
    # Populated only when a supports_audio provider analyzes the conversation
    # clip, capturing what the audio reveals beyond the transcript text.
    # Distinct from summary_text so provenance stays clear.
    audio_speaker_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_tone: Mapped[str | None] = mapped_column(String(16), nullable=True)
    audio_non_verbal: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    audio_gist: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_analyzed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Summary(Base):
    """Window-level recap generated by a VLM over many observations.

    A row is the closing artifact of a periodic timer or event window.
    Holds the narrative text, the IDs of source observations and
    transcripts, and aggregated facts (people seen, plates, object
    counts) so the UI can render the recap without joining back to
    every source row.
    """

    __tablename__ = "summaries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cameras.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # periodic | event
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trigger_reason: Mapped[str] = mapped_column(String(32), nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_observation_ids: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_transcript_ids: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    people_seen: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    plates_seen: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    object_counts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
