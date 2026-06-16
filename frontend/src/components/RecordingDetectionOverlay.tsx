"use client";

// Draws detection boxes over a recording's <video> as it plays, by fetching
// the observations for the clip's time window and showing the ones active at
// the current playback time. Pure browser overlay (no re-encode) — the
// download-with-annotations path is the separate "bake it into the file" one.

import { useEffect, useMemo, useState, type RefObject } from "react";
import { useAuth } from "@/lib/auth";

interface Box {
  label: string;
  bbox: number[];
}
interface Frame {
  offset: number; // seconds from clip start
  boxes: Box[];
}

const PET = new Set(["cat", "dog", "bird", "rabbit", "horse"]);
const VEHICLE = new Set(["car", "truck", "bus", "motorcycle", "bicycle", "train"]);

function colorFor(label: string): string {
  const l = (label || "").toLowerCase();
  if (l === "person") return "rgb(59,130,246)";   // blue
  if (PET.has(l)) return "rgb(70,200,70)";          // green
  if (VEHICLE.has(l)) return "rgb(250,185,15)";     // amber
  return "rgb(160,160,160)";
}

export function RecordingDetectionOverlay({
  cameraId,
  startedAt,
  endedAt,
  durationSeconds,
  camWidth,
  camHeight,
  videoRef,
  draw = true,
  seekLabel = null,
  onTargets,
}: {
  cameraId: string;
  startedAt: string;
  endedAt: string | null;
  durationSeconds: number | null;
  camWidth?: number | null;
  camHeight?: number | null;
  videoRef: RefObject<HTMLVideoElement | null>;
  // Draw the boxes (off = data still loads so the seek targets stay live).
  draw?: boolean;
  // When set, seek targets are only frames containing this label; else any.
  seekLabel?: string | null;
  // Reports the sorted offsets (seconds) the "jump to next detection" controls seek to.
  onTargets?: (offsets: number[]) => void;
}) {
  const { authFetch } = useAuth();
  const [frames, setFrames] = useState<Frame[]>([]);
  const [t, setT] = useState(0);
  const [dims, setDims] = useState<{ w: number; h: number }>({ w: 0, h: 0 });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const base = new Date(startedAt).getTime();
      const end = endedAt
        ? endedAt
        : new Date(base + (durationSeconds || 3600) * 1000).toISOString();
      try {
        const res = await authFetch(
          `/api/observations?camera_id=${cameraId}&from=${encodeURIComponent(startedAt)}` +
            `&to=${encodeURIComponent(end)}&limit=200`
        );
        if (!res.ok || cancelled) return;
        const obs = (await res.json()) as {
          started_at: string;
          object_detections?: { objects?: { label: string; bbox: number[] }[] };
        }[];
        const fr: Frame[] = obs
          .map((o) => ({
            offset: Math.max(0, (new Date(o.started_at).getTime() - base) / 1000),
            boxes: (o.object_detections?.objects || [])
              .filter((d) => Array.isArray(d.bbox) && d.bbox.length === 4)
              .map((d) => ({ label: d.label, bbox: d.bbox })),
          }))
          .sort((a, b) => a.offset - b.offset);
        if (!cancelled) setFrames(fr);
      } catch {
        /* silent */
      }
    })();
    return () => { cancelled = true; };
  }, [cameraId, startedAt, endedAt, durationSeconds, authFetch]);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onTime = () => setT(v.currentTime);
    const onMeta = () => setDims({ w: v.videoWidth, h: v.videoHeight });
    if (v.videoWidth) onMeta();
    v.addEventListener("timeupdate", onTime);
    v.addEventListener("loadedmetadata", onMeta);
    return () => {
      v.removeEventListener("timeupdate", onTime);
      v.removeEventListener("loadedmetadata", onMeta);
    };
  }, [videoRef]);

  // Report the offsets the "jump to next detection" controls seek to: frames
  // that contain the chosen object (or any detection when no object is set).
  useEffect(() => {
    if (!onTargets) return;
    const want = (seekLabel || "").toLowerCase();
    const targets = frames
      .filter((f) =>
        f.boxes.length > 0 &&
        (want ? f.boxes.some((b) => b.label.toLowerCase() === want) : true)
      )
      .map((f) => f.offset);
    onTargets(targets);
  }, [frames, seekLabel, onTargets]);

  // The active observation is the most recent one at or before the playhead;
  // its boxes hold until the next observation.
  const active = useMemo(() => {
    let cur: Frame | null = null;
    for (const f of frames) {
      if (f.offset <= t + 0.25) cur = f;
      else break;
    }
    return cur;
  }, [frames, t]);

  if (!draw || !active || active.boxes.length === 0) return null;

  // The recording <video> renders at its intrinsic aspect with width:100% and
  // height:auto, so its box is the content (no letterbox): bbox% maps directly.
  // Frame dims come from the camera config, falling back to the decoded video
  // size (captured on loadedmetadata, so never read the ref during render).
  const fw = camWidth || dims.w || 1920;
  const fh = camHeight || dims.h || 1080;

  return (
    <div className="absolute inset-0 pointer-events-none">
      {active.boxes.map((b, i) => {
        const [x1, y1, x2, y2] = b.bbox;
        const color = colorFor(b.label);
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `${(x1 / fw) * 100}%`,
              top: `${(y1 / fh) * 100}%`,
              width: `${((x2 - x1) / fw) * 100}%`,
              height: `${((y2 - y1) / fh) * 100}%`,
              border: `2px solid ${color}`,
              borderRadius: "2px",
            }}
          >
            <span
              style={{
                position: "absolute", top: "-16px", left: 0, fontSize: "10px",
                lineHeight: "14px", padding: "0 3px", backgroundColor: color,
                color: "#000", borderRadius: "2px", whiteSpace: "nowrap", fontWeight: 600,
              }}
            >
              {b.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}
