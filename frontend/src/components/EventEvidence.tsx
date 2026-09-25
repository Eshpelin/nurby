"use client";

/**
 * Evidence-first rendering of a fired event's payload: what the camera
 * actually saw (snapshot with detection boxes), a path to the footage,
 * and a plain-language summary. The raw JSON stays available behind a
 * disclosure for debugging, never as the primary surface.
 */

import { useEffect, useMemo, useState } from "react";
import { useAuth } from "@/lib/auth";

type Payload = Record<string, unknown>;

interface DetectionObject {
  label?: string;
  confidence?: number;
}

interface FaceDetection {
  person_name?: string | null;
}

/** Build a one-line human summary of what the payload describes. */
export function summarizePayload(payload: Payload): string {
  // Camera availability events read as a sentence, not detections.
  if (payload.event_kind === "camera_status") {
    const what = payload.camera_status === "online" ? "came back online" : "went offline";
    const reason = payload.status_reason ? ` (${payload.status_reason})` : "";
    return `Camera ${what}${reason}.`;
  }

  const parts: string[] = [];
  const vlm = (payload.vlm_description as string) || "";
  if (vlm) parts.push(vlm);

  const objects =
    ((payload.object_detections as { objects?: DetectionObject[] })?.objects) || [];
  if (objects.length > 0) {
    const counts = new Map<string, number>();
    for (const o of objects) {
      const label = o.label || "object";
      counts.set(label, (counts.get(label) || 0) + 1);
    }
    const described = [...counts.entries()]
      .map(([label, n]) => (n === 1 ? `1 ${label}` : `${n} ${label}s`))
      .join(", ");
    parts.push(`Detected ${described}.`);
  }

  const faces =
    ((payload.person_detections as { faces?: FaceDetection[] })?.faces) || [];
  if (faces.length > 0) {
    const named = [...new Set(faces.map((f) => f.person_name).filter(Boolean))] as string[];
    const unknown = faces.filter((f) => !f.person_name).length;
    const faceParts: string[] = [];
    if (named.length > 0) faceParts.push(`recognized ${named.join(", ")}`);
    if (unknown > 0) faceParts.push(`${unknown} unrecognized ${unknown === 1 ? "face" : "faces"}`);
    if (faceParts.length > 0) {
      const joined = faceParts.join(" and ");
      parts.push(joined.charAt(0).toUpperCase() + joined.slice(1) + ".");
    }
  }

  const audio = payload.audio_event as { label?: string } | undefined;
  if (audio?.label) parts.push(`Heard: ${audio.label.replace(/_/g, " ")}.`);

  if (parts.length === 0) {
    const motion = payload.motion_score as number | undefined;
    if (motion != null) return `Motion detected (score ${Math.round(motion * 100)}%).`;
    return "";
  }
  return parts.join(" ");
}

export function EventEvidence({
  payload,
  isAdmin = false,
  recordingId: eventRecordingId,
  cameraId,
  firedAt,
}: {
  payload: Payload;
  isAdmin?: boolean;
  recordingId?: string | null;
  cameraId?: string | null;
  firedAt?: string | null;
}) {
  const { token } = useAuth();
  const [imgFailed, setImgFailed] = useState(false);
  const [imgLightbox, setImgLightbox] = useState(false);
  const [resolvedRecordingId, setResolvedRecordingId] = useState<string | null>(null);
  const [clipPending, setClipPending] = useState(false);

  const summary = useMemo(() => summarizePayload(payload), [payload]);
  const observationId = (payload.observation_id as string) || null;
  const recordingId = eventRecordingId || (payload.recording_id as string) || resolvedRecordingId;
  const resolvedCameraId = cameraId || (payload.camera_id as string) || null;
  const eventTime = firedAt || (payload.timestamp as string) || null;

  useEffect(() => {
    if (eventRecordingId || payload.recording_id || !resolvedCameraId || !eventTime || !token) {
      setClipPending(false);
      return;
    }

    const triggerMs = new Date(eventTime).getTime();
    if (!Number.isFinite(triggerMs)) return;
    let cancelled = false;
    const young = () => Date.now() - triggerMs < 6 * 60 * 1000;

    const resolve = async () => {
      try {
        const from = new Date(triggerMs - 3000).toISOString();
        const to = new Date(triggerMs + 3000).toISOString();
        const response = await fetch(
          `/api/recordings?camera_id=${encodeURIComponent(resolvedCameraId)}&from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&limit=5`,
          { headers: { Authorization: `Bearer ${token}` } },
        );
        if (!response.ok) return;
        const data = await response.json();
        const recordings = Array.isArray(data) ? data : data.recordings || [];
        const match = recordings.find((item: Record<string, unknown>) => {
          const start = new Date(String(item.started_at || "")).getTime();
          const end = item.ended_at
            ? new Date(String(item.ended_at)).getTime()
            : start + Number(item.duration_seconds || 0) * 1000;
          return Number.isFinite(start) && triggerMs >= start - 3000 && triggerMs <= end + 3000;
        });
        if (!cancelled && match?.id) {
          setResolvedRecordingId(String(match.id));
          setClipPending(false);
        }
      } catch {
        // The evidence card remains useful if the best-effort lookup fails.
      }
    };

    setClipPending(young());
    void resolve();
    const timer = young() ? window.setInterval(resolve, 30000) : undefined;
    return () => {
      cancelled = true;
      if (timer) window.clearInterval(timer);
    };
  }, [eventRecordingId, eventTime, payload.recording_id, resolvedCameraId, token]);

  const thumbUrl =
    observationId && token
      ? `/api/observations/${observationId}/thumbnail?token=${encodeURIComponent(token)}`
      : null;
  const clipUrl =
    recordingId && token
      ? `/api/recordings/${recordingId}/stream?token=${encodeURIComponent(token)}`
      : null;

  return (
    <div className="space-y-2">
      {summary && <p className="text-sm leading-relaxed">{summary}</p>}

      {thumbUrl && !imgFailed && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={thumbUrl}
          alt="What the camera saw when this alert fired"
          onError={() => setImgFailed(true)}
          onClick={(e) => {
            e.stopPropagation();
            setImgLightbox(true);
          }}
          className="rounded-md border border-border max-h-64 w-auto cursor-zoom-in"
        />
      )}
      {imgLightbox && thumbUrl && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 cursor-zoom-out"
          onClick={(e) => {
            e.stopPropagation();
            setImgLightbox(false);
          }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={thumbUrl} alt="Alert snapshot, full size" className="max-h-[90vh] max-w-[95vw] rounded-md" />
        </div>
      )}

      <div className="flex items-center gap-2">
        {clipUrl && (
          <a
            href={clipUrl}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="px-2 py-1 text-[11px] rounded-md bg-foreground text-background font-medium hover:opacity-90"
          >
            ▶ Watch clip
          </a>
        )}
        {!clipUrl && clipPending && (
          <span className="text-[11px] text-muted-foreground">
            Clip is still being saved. It should appear here shortly.
          </span>
        )}
        {!clipUrl && !clipPending && observationId && (
          <span className="text-[11px] text-muted-foreground">
            No recording covered this moment.
          </span>
        )}
      </div>

      {isAdmin && (
        <details onClick={(e) => e.stopPropagation()}>
          <summary className="text-[10px] text-muted-foreground cursor-pointer select-none hover:text-foreground">
            Developer details
          </summary>
          <pre className="mt-1 text-[10px] font-mono bg-muted/50 rounded p-2 overflow-x-auto max-h-40 overflow-y-auto whitespace-pre-wrap">
            {JSON.stringify(payload, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
