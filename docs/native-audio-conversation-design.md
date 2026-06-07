# Native-audio conversation detection

Status: design + scaffold. native-audio inference is gated on a capable
provider (see "The runtime gap"). the whisper-text path remains the default.

## Goal

Today a conversation is understood from text only. audio is transcribed by
whisper, the transcript segments are grouped by gap into a Conversation, and
a VLM summarizes the text. That loses everything that is in the audio but not
in the words: how many distinct speakers, who overlapped whom, tone and
mood (calm, argument, distress), laughter, crying, raised voices, and speech
the transcriber dropped as low-confidence.

Native-audio conversation detection feeds the raw conversation audio to a
model that ingests audio directly, to extract that structure: speaker count
and turns, overlap, tone, and a short gist grounded in how it sounded, not
just what was said.

## What already exists to build on

- Audio capture -> VAD -> whisper STT -> `Transcript` rows (services/perception/audio/*).
- Conversation grouping by gap + a finalizer that summarizes the text with a VLM (`conversation_finalizer.py`).
- The finalizer already **builds an audio clip for the conversation window** (`build_clip_for_conversation` -> `clip_path`). that clip is exactly the input a native-audio model needs.
- `Conversation` already has `speakers_seen` (video-derived) and a `summary_text`.

So the missing piece is only the analyzer. take the conversation's audio
clip, send it to an audio-capable model, store the structured result.

## The runtime gap (why this is gated)

A native-audio model is available (`gemma3n:e4b`, Gemma's audio+vision
variant, pulls from the ollama registry). But **ollama's generate API
currently accepts only `images`, not audio**, so even with the model pulled
it cannot be fed audio. Native-audio inference therefore needs one of:

- a cloud provider with audio input. Gemini (`gemini-2.0-flash` accepts
  audio), or OpenAI audio models. requires an API key.
- a local runtime that accepts audio input. a future ollama audio API, or a
  direct llama.cpp / transformers server for gemma3n.

Until one of those is configured, the scaffold no-ops and the existing
whisper-text summary stands. nothing regresses.

## Design

A provider gains an **audio capability flag** (`supports_audio`). The
conversation finalizer, after it has the audio clip, asks for an audio
analyzer for the active provider:

- if a `supports_audio` provider is configured -> call it with the clip and a
  structured prompt, parse the result into conversation fields.
- otherwise -> skip, keep the whisper-text summary (today's behavior).

### Analyzer contract

`analyze_conversation_audio(clip_path, transcript_text, provider) -> AudioConversationResult | None`

```
AudioConversationResult:
  speaker_count: int | None
  tone: str | None            # calm | tense | argument | distressed | playful | unclear
  non_verbal: list[str]       # laughter, crying, raised-voice, alarm, music
  gist: str | None            # one sentence grounded in how it sounded
  confidence: float | None
```

The prompt gives the model both the audio and the whisper transcript as a
crib, and asks it to add only what the audio reveals beyond the words.

### Storage

Extend `Conversation` with audio-derived columns, kept distinct from the
text summary so provenance is clear and nothing is overwritten:

- `audio_speaker_count int`
- `audio_tone string(16)`
- `audio_non_verbal json`
- `audio_gist text`
- `audio_analyzed_by string(64)` (provider/model)

The conversation card surfaces tone + speaker count + non-verbal tags next
to the existing text summary.

### Fallback and cost

- Off unless a `supports_audio` provider is active. budgeted the same way as
  the VLM, since it is one model call per finalized conversation.
- The audio clip is bounded (one conversation window), so cost is one call
  per conversation, not per segment.

## Phasing

- **n2.0 (this scaffold)**. the analyzer interface + the `supports_audio`
  provider flag + the finalizer hook with fallback. verified to be a no-op
  when no audio provider exists (no regression).
- **n2.1**. a concrete Gemini/OpenAI audio adapter (cloud, needs a key) that
  fills the analyzer, plus the `Conversation` columns + UI tags.
- **n2.2**. a local gemma3n adapter once a runtime accepts audio (direct
  llama.cpp/transformers server, or ollama audio support).
- **n2.3**. fuse audio tone with the video speaker attribution and the
  PANNs audio events already captured, for a single grounded conversation
  record.

## Open questions

- Send the whole clip or only the speech segments (trim silence to cut cost)?
- Diarization. rely on the model's speaker turns, or pre-segment with a
  dedicated diarizer and pass speaker-tagged audio?
- Privacy. audio analysis is more sensitive than text. should it honor the
  same per-camera `transcript_store` / consent gates (likely yes).
