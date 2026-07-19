// Dashboard data types. Extracted from page.tsx (no behavior change).
import type { ObservationGroup as CoalesceGroup } from "@/lib/observation-grouping";
import type { Journey } from "@/components/JourneyCard";
import type { StreamType } from "@/lib/camera-types";

export interface Camera {
  id: string;
  name: string;
  stream_url: string;
  stream_type: StreamType;
  location_label: string | null;
  status: "offline" | "live" | "recording";
  status_reason?: string | null;
  next_retry_at?: number | null;
  retry_delay_seconds?: number | null;
  width: number | null;
  height: number | null;
  fps: number | null;
  recording_enabled: boolean;
  digest_enabled: boolean;
  digest_period: string;
  audio_capture_enabled?: boolean;
  audio_only?: boolean;
  audio_transcribe_enabled?: boolean;
  created_at: string;
  updated_at: string;
}

export interface Person {
  id: string;
  display_name: string;
}

export interface PersonSummary {
  person_id: string;
  display_name: string;
  relationship: string | null;
  photo_path: string | null;
  total_sightings: number;
  sightings_1h: number;
  sightings_24h: number;
  last_seen_at: string | null;
  last_seen_camera: string | null;
  first_seen_at: string | null;
}

export interface ClusterSummary {
  cluster_id: string;
  auto_label: string;
  auto_label_number: number | null;
  appearance_description: string | null;
  appearance_description_status: string;
  sample_thumbnail_path: string | null;
  sighting_count: number;
  sightings_1h: number;
  sightings_24h: number;
  last_seen_at: string | null;
  last_seen_camera: string | null;
  first_seen_at: string | null;
}

export interface PersonActivityItem {
  observation_id: string;
  camera_id: string;
  camera_name: string | null;
  started_at: string;
  ended_at: string | null;
  vlm_description: string | null;
  thumbnail_path: string | null;
  person_name: string | null;
  match_distance: number | null;
  object_detections: { objects?: { label: string; confidence: number }[] } | null;
}

export interface Recording {
  id: string;
  camera_id: string;
  file_path: string;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  file_size_bytes: number | null;
  thumbnail_path: string | null;
}

export interface FaceDetection {
  person_name: string | null;
  person_id: string | null;
  cluster_id?: string | null;
  match_distance?: number | null;
  bbox?: number[];
}

export interface Observation {
  id: string;
  camera_id: string;
  started_at: string;
  ended_at: string | null;
  object_detections: { objects: Detection[]; count: number } | null;
  person_detections: { faces: FaceDetection[]; count: number } | null;
  vlm_description: string | null;
  vlm_provider: string | null;
  confidence: number | null;
  thumbnail_path: string | null;
  primary_vlm_description?: string | null;
  refined_by_provider_name?: string | null;
  refined_at?: string | null;
}

export interface Detection {
  label: string;
  confidence: number;
  bbox?: number[];
  plate_text?: string | null;
}

export interface StatusLog {
  id: string;
  camera_id: string;
  status: string;
  previous_status: string | null;
  reason: string | null;
  timestamp: string;
}

export interface SearchResult {
  // kind absent on legacy observations endpoint, present on union.
  kind?: "observation" | "transcript" | "conversation" | "summary";
  id: string;
  camera_id: string;
  camera_name: string;
  started_at: string;
  // Observation-only fields.
  object_detections?: { objects: { label: string; confidence: number; plate_text?: string | null }[]; count: number } | null;
  person_detections?: { faces: FaceDetection[]; count: number } | null;
  vlm_description?: string | null;
  confidence?: number | null;
  thumbnail_path?: string | null;
  // Transcript-only fields.
  text?: string | null;
  language?: string | null;
  provider?: string | null;
  // Conversation-only fields.
  summary_text?: string | null;
  transcript_count?: number | null;
  // Summary-only fields.
  summary_kind?: string | null;
  // Common.
  ended_at?: string | null;
  distance?: number | null;
}

export interface Digest {
  period: string;
  period_label: string;
  total_observations: number;
  summary: string;
  highlights: string[];
}

export interface Transcript {
  id: string;
  camera_id: string;
  audio_capture_id: string | null;
  started_at: string;
  ended_at: string;
  text: string;
  language: string | null;
  provider: string;
}

export interface Summary {
  id: string;
  camera_id: string;
  kind: "periodic" | "event" | string;
  started_at: string;
  ended_at: string;
  provider_name: string | null;
  trigger_reason: string;
  summary_text: string;
  people_seen: { name: string; sightings: number; first_seen?: string; last_seen?: string }[] | null;
  plates_seen: string[] | null;
  object_counts: Record<string, number> | null;
}

export interface Incident {
  id: string;
  camera_id: string;
  signature_kind: string;
  signature_key: string;
  started_at: string;
  last_seen_at: string;
  ended_at: string | null;
  finalized: boolean;
  occurrence_count: number;
  peak_observation_id: string | null;
  observation_ids: string[] | null;
  thumbnails: { obs_id: string; path: string | null; ts: string }[] | null;
  summary_text: string | null;
  summary_provider_name: string | null;
}

export interface Conversation {
  id: string;
  camera_id: string;
  started_at: string;
  ended_at_provisional: string;
  ended_at: string | null;
  transcript_count: number;
  finalized: boolean;
  summary_text: string | null;
  cleaned_text: string | null;
  summary_provider_name: string | null;
  has_clip?: boolean;
  clip_duration_ms?: number | null;
}

export interface TimelineEntry {
  id: string;
  type:
    | "recording"
    | "observation"
    | "observation_group"
    | "incident"
    | "journey"
    | "status"
    | "search_result"
    | "notification"
    | "transcript"
    | "summary"
    | "conversation";
  camera_id: string;
  timestamp: string;
  data:
    | Recording
    | Observation
    | CoalesceGroup
    | Incident
    | Journey
    | StatusLog
    | SearchResult
    | Notification
    | Transcript
    | Summary
    | Conversation;
}

export interface ActivityEvent {
  id: string;
  timestamp: string;
  summary: string;
  icon: "person" | "object" | "scene";
}

export interface Notification {
  id: string;
  message: string;
  severity: string;
  rule_id: string | null;
  camera_id: string | null;
  observation_id: string | null;
  read: boolean;
  created_at: string;
}

export type TimeRange = "today" | "7d" | "30d";
export type EventFilter = "recordings" | "observations" | "status" | "transcripts" | "conversations" | "summaries";
