// Settings page data types + pure storage helpers. Extracted from
// page.tsx (no behavior change).

export interface Provider {
  id: string;
  name: string;
  kind: string;
  base_url: string;
  default_model: string | null;
  active: boolean;
  max_input_tokens: number | null;
  max_output_tokens: number | null;
  created_at: string;
}

export interface InviteCreator {
  id: string;
  email: string;
  display_name: string | null;
}

export interface InviteRedemption {
  user_id: string;
  email: string;
  display_name: string | null;
  role: string;
  is_active: boolean;
  redeemed_at: string;
}

export interface InviteKey {
  id: string;
  key: string;
  role: string;
  camera_ids: string[] | null;
  max_uses: number;
  use_count: number;
  expires_at: string | null;
  created_at: string;
  created_by: InviteCreator | null;
  redemptions: InviteRedemption[];
}

export type InviteKeyStatus = "active" | "expired" | "full";

// Derive the lifecycle status of a key from its expiry and usage. Used to
// render the status pill and to sort/emphasize keys in the manager.
export function inviteKeyStatus(ik: InviteKey): InviteKeyStatus {
  if (ik.expires_at !== null && new Date(ik.expires_at) < new Date()) return "expired";
  if (ik.use_count >= ik.max_uses) return "full";
  return "active";
}

export interface Camera {
  id: string;
  name: string;
}

// One row from GET /api/shares (anonymous share links the user created).
// `label` carries the human context ("Front door · Jun 3, 2:30 PM") set at
// creation time; the raw link itself is never stored or re-shown.
export interface ShareRow {
  id: string;
  kind: "recording" | "observation" | "event";
  label: string | null;
  max_views: number | null;
  view_count: number;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
  last_accessed_at: string | null;
  status: "active" | "expired" | "revoked" | "exhausted";
}

export const SHARE_KIND_LABEL: Record<ShareRow["kind"], string> = {
  recording: "Recording",
  observation: "Frame",
  event: "Event",
};

export interface CameraStorage {
  camera_id: string;
  camera_name: string;
  recording_count: number;
  recording_bytes: number;
  observation_count: number;
  retention_mode: string;
  retention_days: number;
  retention_gb: number;
}

export interface StorageStats {
  cameras: CameraStorage[];
  total_recording_bytes: number;
  total_observations: number;
}

// PROVIDER_KINDS and ALL_PROVIDERS now live in @/lib/provider-presets so
// the onboarding wizard and this screen share one catalog.

export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

export function retentionLabel(cam: CameraStorage): string {
  if (cam.retention_mode === "time") return "Keep " + cam.retention_days + " days";
  if (cam.retention_mode === "size") return "Max " + cam.retention_gb + " GB";
  return "No limit";
}

export function usagePercent(cam: CameraStorage): number | null {
  if (cam.retention_mode === "size" && cam.retention_gb > 0) {
    const limitBytes = cam.retention_gb * 1024 * 1024 * 1024;
    return (cam.recording_bytes / limitBytes) * 100;
  }
  return null;
}

export function barColor(percent: number | null): string {
  if (percent === null) return "bg-blue-500";
  if (percent >= 80) return "bg-red-500";
  if (percent >= 50) return "bg-yellow-500";
  return "bg-green-500";
}
