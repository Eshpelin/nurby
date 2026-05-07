/**
 * Minimal observation shape used by the coalescer. Page-level
 * Observation interface in src/app/page.tsx may carry more fields,
 * but the grouper only needs these.
 */

export interface FaceDetection {
  person_name: string | null;
  person_id?: string | null;
  cluster_id?: string | null;
  match_distance?: number | null;
  bbox?: number[];
}

export interface Detection {
  label: string;
  confidence: number;
  bbox?: number[];
  plate_text?: string | null;
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
