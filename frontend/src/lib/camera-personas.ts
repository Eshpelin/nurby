/**
 * Camera persona types.
 *
 * The persona definitions themselves live in shared/camera_personas.py
 * and are served by GET /api/cameras/personas, so web and mobile apply
 * the same bundle. This file keeps the TypeScript shape and a hook to
 * load them. Add new personas on the backend; both clients pick them up.
 */

export interface PersonaPatch {
  // Detection
  detect_objects?: boolean;
  detect_faces?: boolean;
  scene_mode?: "indoor" | "outdoor";
  object_confidence?: number;
  detection_models?: { model: string; confidence: number; enabled: boolean; label_filter: string[] }[];
  yolo_world_prompts?: string[];
  privacy_zone_targets?: string[];
  // VLM
  vlm_trigger?: "always" | "on_object";
  vlm_trigger_objects?: string[];
  vlm_max_tokens?: number;
  // Recording
  recording_mode?: "off" | "always" | "on_motion" | "on_object" | "clip";
  recording_trigger_objects?: string[];
  recording_clip_pre?: number;
  recording_clip_post?: number;
  // Retention
  retention_mode?: "none" | "time" | "size";
  retention_days?: number;
  retention_gb?: number;
  // Audio
  audio_capture_enabled?: boolean;
  audio_transcribe_enabled?: boolean;
  audio_store_raw?: boolean;
  audio_retention_days?: number;
  transcript_retention_days?: number;
  // Summaries
  summary_mode?: "off" | "periodic" | "event" | "both";
  summary_period_seconds?: number;
  summary_event_quiet_seconds?: number;
  summary_event_trigger_objects?: string[];
  summary_event_min_duration_seconds?: number;
  // Conversations
  conversation_gap_seconds?: number;
  conversation_summary_enabled?: boolean;
}

export interface Persona {
  id: string;
  label: string;
  hint: string;
  iconPath: string; // svg `d` for a 24x24 icon (icon_path on the wire)
  patch: PersonaPatch;
}

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

/**
 * Load personas from the API once per mount. An empty list while loading
 * or on error: the picker renders nothing rather than a stale copy.
 */
export function usePersonas(): Persona[] {
  const { authFetch } = useAuth();
  const [personas, setPersonas] = useState<Persona[]>([]);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await authFetch("/api/cameras/personas");
        if (!res.ok) return;
        const body = (await res.json()) as {
          personas: Array<{ id: string; label: string; hint: string; icon_path: string; patch: PersonaPatch }>;
        };
        if (cancelled) return;
        setPersonas(
          body.personas.map((p) => ({
            id: p.id,
            label: p.label,
            hint: p.hint,
            iconPath: p.icon_path,
            patch: p.patch,
          })),
        );
      } catch {
        // Leave empty. A persona is a convenience, never a blocker.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [authFetch]);
  return personas;
}
