// Dashboard formatting + detection-summary helpers. Pure functions
// extracted from page.tsx (no behavior change).
import type { ActivityEvent, Observation } from "./dashboard-types";
import { formatWith } from "@/lib/time";

export function formatTime(iso: string): string {
  return formatWith(new Date(iso), { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatDate(iso: string): string {
  return formatWith(new Date(iso), { weekday: "short", month: "short", day: "numeric" });
}

export function hourBucketKey(iso: string): string {
  const d = new Date(iso);
  d.setMinutes(0, 0, 0);
  return d.toISOString();
}

export function formatHourBucket(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const today = new Date(now); today.setHours(0, 0, 0, 0);
  const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1);
  const bucketDay = new Date(d); bucketDay.setHours(0, 0, 0, 0);
  const hr = formatWith(d, { hour: "numeric", hour12: true });
  let day = "";
  if (bucketDay.getTime() === today.getTime()) day = "Today";
  else if (bucketDay.getTime() === yesterday.getTime()) day = "Yesterday";
  else day = formatWith(d, { weekday: "short", month: "short", day: "numeric" });
  return `${day} \u00b7 ${hr}`;
}

export function formatDuration(seconds: number | null): string {
  if (!seconds) return "0s";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m === 0 ? `${s}s` : `${m}m ${s}s`;
}

export function formatSize(bytes: number | null): string {
  if (!bytes) return "";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function extractStreamName(streamUrl: string): string {
  try {
    const path = streamUrl.replace(/\/+$/, "");
    const lastSlash = path.lastIndexOf("/");
    return lastSlash >= 0 ? path.slice(lastSlash + 1) : path;
  } catch {
    return streamUrl;
  }
}

export function summarizeDetections(obs: Observation): string {
  const parts: string[] = [];

  // Person names first
  if (obs.person_detections?.faces) {
    const named = obs.person_detections.faces.filter((f) => f.person_name);
    const unnamed = obs.person_detections.faces.filter((f) => !f.person_name);
    for (const f of named) {
      parts.push(f.person_name!);
    }
    if (unnamed.length > 0) {
      parts.push(unnamed.length === 1 ? "Unknown person" : `${unnamed.length} unknown people`);
    }
  }

  // License plates
  if (obs.object_detections?.objects) {
    for (const d of obs.object_detections.objects) {
      if (d.label === "license_plate" && d.plate_text) {
        parts.push(`plate ${d.plate_text}`);
      }
    }
  }

  // Object counts (skip person since we handled faces above, skip license_plate since handled)
  if (obs.object_detections?.objects && obs.object_detections.objects.length > 0) {
    const counts: Record<string, number> = {};
    for (const d of obs.object_detections.objects) {
      if (d.label === "person" || d.label === "license_plate") continue;
      counts[d.label] = (counts[d.label] || 0) + 1;
    }
    const objectParts = Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .map(([label, count]) => (count === 1 ? label : `${count} ${label}s`));
    parts.push(...objectParts);
  }

  if (parts.length === 0) {
    return obs.vlm_description
      ? obs.vlm_description.split(/\.\s/)[0].slice(0, 60)
      : "Motion detected";
  }

  return parts.join(", ") + " detected";
}

export function observationToEvents(obs: Observation): ActivityEvent[] {
  const events: ActivityEvent[] = [];

  if (obs.person_detections?.faces) {
    const named = obs.person_detections.faces.filter((f) => f.person_name);
    const unnamed = obs.person_detections.faces.filter((f) => !f.person_name);

    for (const face of named) {
      events.push({
        id: `${obs.id}-person-${face.person_name}`,
        timestamp: obs.started_at,
        summary: `${face.person_name} spotted`,
        icon: "person",
      });
    }

    if (unnamed.length > 0 && named.length === 0) {
      events.push({
        id: `${obs.id}-unknown-persons`,
        timestamp: obs.started_at,
        summary: unnamed.length === 1 ? "Unknown person detected" : `${unnamed.length} unknown people detected`,
        icon: "person",
      });
    }
  }

  if (obs.object_detections?.objects && obs.object_detections.objects.length > 0) {
    const counts: Record<string, number> = {};
    for (const obj of obs.object_detections.objects) {
      counts[obj.label] = (counts[obj.label] || 0) + 1;
    }
    const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 2);
    const parts = sorted.map(([label, count]) => count === 1 ? label : `${count} ${label}s`);

    if (events.length === 0 && parts.length > 0) {
      // Prefer the VLM caption when available. Detections become a subtitle.
      let summary = parts.join(", ") + " detected";
      if (obs.vlm_description) {
        let desc = obs.vlm_description.split(/\.\s/)[0];
        if (desc.length > 80) desc = desc.slice(0, 77) + ".";
        summary = desc;
      }
      events.push({
        id: `${obs.id}-objects`,
        timestamp: obs.started_at,
        summary,
        icon: "object",
      });
    }
  }

  if (events.length === 0 && obs.vlm_description) {
    let desc = obs.vlm_description.split(/\.\s/)[0];
    if (desc.length > 80) desc = desc.slice(0, 77) + ".";
    events.push({
      id: `${obs.id}-scene`,
      timestamp: obs.started_at,
      summary: desc,
      icon: "scene",
    });
  }

  return events;
}

export function statusColor(status: string): string {
  const map: Record<string, string> = { live: "bg-green-500", recording: "bg-danger", offline: "bg-gray-500", error: "bg-warning" };
  return map[status] || "bg-gray-500";
}

export function statusLabel(status: string): string {
  const map: Record<string, string> = { live: "Online", recording: "Recording", offline: "Offline", error: "Error" };
  return map[status] || status;
}
