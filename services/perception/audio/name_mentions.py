"""Conservative spoken-name hypotheses for the unified identity review flow.

This module treats a name in a transcript as evidence about a nearby visual
subject, not as proof of the speaker's identity. It deliberately uses small,
deterministic patterns until a language model/parser can be versioned and
evaluated against household speech.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.perception.associator import record_pairing
from shared.models import EntityAssociation, Observation, Person, Transcript

_NAME = r"([A-Za-z][A-Za-z'-]{1,30})"
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("direct_address", re.compile(rf"^(?:hey|hi|hello)\s+{_NAME}\b", re.IGNORECASE)),
    ("direct_address", re.compile(rf"\b{_NAME},\s+(?:can|could|would|please|come|look|wait)\b", re.IGNORECASE)),
    ("third_person", re.compile(rf"\b(?:tell|ask|call)\s+{_NAME}\b", re.IGNORECASE)),
    ("third_person", re.compile(rf"\bwhere is\s+{_NAME}\b", re.IGNORECASE)),
)
_STOPWORDS = {
    "the", "this", "that", "there", "please", "come", "look", "wait",
    "can", "could", "would", "where", "is", "tell", "ask", "call",
}
_NEGATION = re.compile(r"(?:\b(?:don't|dont|do not|not|never|no)\s+)$", re.IGNORECASE)


def extract_name_mentions(text: str) -> list[dict[str, str]]:
    """Extract context-supported name candidates without guessing every noun."""
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text or ""):
            # A request not to address/contact someone is not evidence that
            # the nearby person has that name.
            if _NEGATION.search((text or "")[:match.start()]):
                continue
            name = match.group(1).strip(" '").strip()
            normalized = name.casefold()
            if normalized in _STOPWORDS or len(normalized) < 2:
                continue
            key = (normalized, kind)
            if key in seen:
                continue
            seen.add(key)
            found.append({
                "name": name,
                "normalized": normalized,
                "kind": kind,
                "span": match.group(0),
                "span_start": str(match.start()),
                "span_end": str(match.end()),
            })
    return found


def timing_for_span(words: list[dict] | None, text: str, start: int, end: int) -> list[dict]:
    """Return provider word timings that overlap a transcript character span.

    Providers disagree on word keys and may omit timing entirely.  We use the
    stored word text to derive character offsets, then return only the words
    supporting this mention; missing timing simply yields an empty list.
    """
    if not words:
        return []
    cursor = 0
    result: list[dict] = []
    for word in words:
        value = str(word.get("word") or word.get("text") or "").strip()
        if not value:
            continue
        position = text.casefold().find(value.casefold(), cursor)
        if position < 0:
            continue
        word_end = position + len(value)
        cursor = word_end
        if position < end and word_end > start:
            timing = {key: word.get(key) for key in ("word", "text", "start", "end") if word.get(key) is not None}
            if timing:
                result.append(timing)
    return result


async def _nearby_subjects(
    db: AsyncSession, transcript: Transcript,
) -> list[dict[str, object]]:
    window = timedelta(seconds=90)
    rows = (
        await db.execute(
            select(Observation)
            .where(Observation.camera_id == transcript.camera_id)
            .where(Observation.started_at <= transcript.ended_at + window)
            .where(Observation.started_at >= transcript.started_at - window)
            .order_by(Observation.started_at.asc())
            .limit(100)
        )
    ).scalars().all()
    person_ids: set[uuid.UUID] = set()
    for observation in rows:
        for face in ((observation.person_detections or {}).get("faces") or []):
            if face.get("person_id"):
                try:
                    person_ids.add(uuid.UUID(str(face["person_id"])))
                except (ValueError, TypeError):
                    pass
    people = (
        await db.execute(select(Person).where(Person.id.in_(person_ids)))
    ).scalars().all() if person_ids else []
    names = {str(person.id): (person.nickname or person.display_name) for person in people}

    subjects: dict[tuple[str, str], dict[str, object]] = {}
    for observation in rows:
        for face in ((observation.person_detections or {}).get("faces") or []):
            person_id = face.get("person_id")
            cluster_id = face.get("cluster_id")
            if person_id and str(person_id) in names:
                key = ("person", names[str(person_id)])
            elif cluster_id:
                key = ("cluster", str(cluster_id))
            else:
                continue
            subject = subjects.setdefault(key, {
                "kind": key[0],
                "key": key[1],
                "observation_ids": [],
            })
            if str(observation.id) not in subject["observation_ids"]:
                subject["observation_ids"].append(str(observation.id))
    return list(subjects.values())


async def process_transcript_name_mentions(db: AsyncSession, transcript: Transcript) -> int:
    """Persist candidate name associations for one retained transcript."""
    if transcript.filtered:
        return 0
    mentions = extract_name_mentions(transcript.text)
    if not mentions:
        return 0
    subjects = await _nearby_subjects(db, transcript)
    if not subjects:
        return 0

    created = 0
    for mention in mentions:
        for subject in subjects:
            edge = await record_pairing(
                db,
                subject_kind=str(subject["kind"]),
                subject_key=str(subject["key"]),
                object_kind="name",
                object_key=mention["normalized"],
                object_label=mention["name"],
                relation="possibly_named",
                when=transcript.started_at,
                tz_name="UTC",
                min_days=2,
                camera_id=str(transcript.camera_id),
                episode_key=f"transcript:{transcript.id}:{subject['kind']}:{subject['key']}",
                observation_ids=list(subject["observation_ids"]),
                camera_ids=[str(transcript.camera_id)],
                evidence_metadata={
                    "transcript_id": str(transcript.id),
                    "mention_kind": mention["kind"],
                    "name_span": mention["span"],
                    "span_start": int(mention["span_start"]),
                    "span_end": int(mention["span_end"]),
                    "word_timing": timing_for_span(
                        transcript.words,
                        transcript.text,
                        int(mention["span_start"]),
                        int(mention["span_end"]),
                    ),
                    "segment_started_at": transcript.started_at.isoformat(),
                    "segment_ended_at": transcript.ended_at.isoformat(),
                    "provider": transcript.provider,
                    "model": transcript.model,
                    "parser_version": "name-context-v1",
                },
                evidence_kind="audio_name_mention",
                evidence_explanation="A transcript near this visual subject contained a context-supported name mention.",
            )
            if edge is not None:
                created += 1
    return created
