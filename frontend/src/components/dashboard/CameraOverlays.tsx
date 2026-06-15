"use client";

// Live camera-tile overlays (AI-analyzing shimmer, YOLO + pose
// detection overlay, mini PTZ control). Extracted from page.tsx with
// no behavior change.
import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useWSSubscribe } from "@/lib/ws";
import type { Observation } from "@/app/dashboard-types";

// ── Detection Overlay ──

export const DEFAULT_FRAME_WIDTH = 1920;
export const DEFAULT_FRAME_HEIGHT = 1080;
const DETECTION_FADE_MS = 3500;
const DETECTION_POLL_MS = 700;

interface OverlayDetection {
  label: string;
  bbox: number[];
  color: string;
  borderColor: string;
}

// COCO-17 keypoint skeleton edges (nose/eyes/ears, shoulders-elbows-wrists,
// hips-knees-ankles) for the live pose overlay.
const COCO_EDGES: [number, number][] = [
  [0, 1], [0, 2], [1, 3], [2, 4],
  [5, 6], [5, 7], [7, 9], [6, 8], [8, 10],
  [5, 11], [6, 12], [11, 12],
  [11, 13], [13, 15], [12, 14], [14, 16],
];

export function AnalyzingShimmer({ cameraId }: { cameraId: string }) {
  // A slow light sweep over the video while a VLM call for this camera is
  // queued or running, so "the AI is looking at this right now" is visible
  // on the tile itself, not just in a badge.
  const [active, setActive] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useWSSubscribe(
    "vlm_status",
    (data) => {
      const status = (data as { vlm?: { status?: string } }).vlm?.status;
      const busy = status === "queued" || status === "processing" || status === "refining";
      setActive(busy);
      if (timerRef.current) clearTimeout(timerRef.current);
      if (busy) {
        // Safety: never shimmer forever if the idle message is lost.
        timerRef.current = setTimeout(() => setActive(false), 60_000);
      }
    },
    cameraId
  );
  if (!active) return null;
  return (
    <div className="absolute inset-0 z-[4] pointer-events-none overflow-hidden rounded-[inherit]">
      <div
        className="absolute inset-y-0 w-1/3"
        style={{
          background:
            "linear-gradient(90deg, transparent, rgba(139,92,246,0.18), transparent)",
          animation: "nurby-scan 2.2s linear infinite",
        }}
      />
      <style jsx>{`
        @keyframes nurby-scan {
          from { left: -33%; }
          to { left: 100%; }
        }
      `}</style>
    </div>
  );
}

export function DetectionOverlay({ cameraId, visible, frameWidth, frameHeight }: {
  cameraId: string;
  visible: boolean;
  frameWidth: number;
  frameHeight: number;
}) {
  const { authFetch } = useAuth();
  const [detections, setDetections] = useState<OverlayDetection[]>([]);
  const [lastUpdated, setLastUpdated] = useState(0);
  const [faded, setFaded] = useState(false);
  const lastObsIdRef = useRef<string | null>(null);
  // Live pose skeletons from the HAR pipeline (person_actions WS).
  const [skeletons, setSkeletons] = useState<{
    people: { keypoints?: number[][]; bbox?: number[] | null; action?: string; person_name?: string | null }[];
    width: number;
    height: number;
    ts: number;
  } | null>(null);
  useWSSubscribe(
    "person_actions",
    (data) => {
      const msg = data as { people?: { keypoints?: number[][] }[]; width?: number; height?: number };
      const withPose = (msg.people || []).filter((p) => (p.keypoints || []).length > 0);
      setSkeletons(
        withPose.length > 0
          ? { people: withPose, width: msg.width || frameWidth, height: msg.height || frameHeight, ts: Date.now() }
          : null
      );
    },
    cameraId
  );
  useEffect(() => {
    // Skeletons fade out when HAR stops sending updates (person left frame).
    if (!skeletons) return;
    const t = setTimeout(() => setSkeletons(null), 6000);
    return () => clearTimeout(t);
  }, [skeletons]);

  useEffect(() => {
    if (!visible) return;

    let cancelled = false;

    async function poll() {
      try {
        // Fast lane first. Live YOLO cache refreshes per frame.
        const liveRes = await authFetch(`/api/cameras/${cameraId}/live-detections`);
        if (liveRes.ok && !cancelled) {
          const live = await liveRes.json() as {
            width: number;
            height: number;
            detections?: { label: string; confidence: number; bbox: number[] }[];
          };
          if (!cancelled && live.detections && live.detections.length > 0) {
            const boxes: OverlayDetection[] = live.detections.map((d) => ({
              label: `${d.label} ${Math.round(d.confidence * 100)}%`,
              bbox: d.bbox,
              color: "rgba(34, 197, 94, 0.15)",
              borderColor: "rgb(34, 197, 94)",
            }));
            setDetections(boxes);
            setLastUpdated(Date.now());
            setFaded(false);
            return;
          }
        }

        // Fallback. Observation record (slower cadence, includes faces).
        const res = await authFetch(`/api/observations?camera_id=${cameraId}&limit=1`);
        if (!res.ok || cancelled) return;
        const obs: Observation[] = await res.json();
        if (cancelled || obs.length === 0) return;

        const latest = obs[0];
        if (latest.id === lastObsIdRef.current) return;
        lastObsIdRef.current = latest.id;

        const boxes: OverlayDetection[] = [];

        if (latest.object_detections?.objects) {
          for (const obj of latest.object_detections.objects) {
            if (obj.bbox && obj.bbox.length === 4) {
              boxes.push({
                label: `${obj.label} ${Math.round(obj.confidence * 100)}%`,
                bbox: obj.bbox,
                color: "rgba(34, 197, 94, 0.15)",
                borderColor: "rgb(34, 197, 94)",
              });
            }
          }
        }

        if (latest.person_detections?.faces) {
          for (const face of latest.person_detections.faces) {
            if (face.bbox && face.bbox.length === 4) {
              const isKnown = !!face.person_name;
              boxes.push({
                label: face.person_name || "Unknown",
                bbox: face.bbox,
                color: isKnown ? "rgba(59, 130, 246, 0.15)" : "rgba(234, 179, 8, 0.15)",
                borderColor: isKnown ? "rgb(59, 130, 246)" : "rgb(234, 179, 8)",
              });
            }
          }
        }

        if (boxes.length > 0) {
          setDetections(boxes);
          setLastUpdated(Date.now());
          setFaded(false);
        }
      } catch { /* silent */ }
    }

    poll();
    const interval = setInterval(poll, DETECTION_POLL_MS);
    return () => { cancelled = true; clearInterval(interval); };
  }, [cameraId, visible, authFetch]);

  useEffect(() => {
    if (lastUpdated === 0) return;
    const timer = setTimeout(() => setFaded(true), DETECTION_FADE_MS);
    return () => clearTimeout(timer);
  }, [lastUpdated]);

  const hasSkeletons = !!skeletons && skeletons.people.length > 0;
  if (!visible || (detections.length === 0 && !hasSkeletons)) return null;

  // Overlay sits inside the feed container which is always 16:9. The video
  // itself is rendered `object-contain`, so it occupies a centered rect
  // with the camera's native aspect ratio. Compute that inner rect so bbox
  // percentages align with real pixels instead of stretching across the
  // letterbox bands.
  const frameAspect = frameWidth / frameHeight;
  const containerAspect = 16 / 9;
  let innerLeft = 0;
  let innerTop = 0;
  let innerW = 100;
  let innerH = 100;
  if (frameAspect > containerAspect) {
    innerH = (containerAspect / frameAspect) * 100;
    innerTop = (100 - innerH) / 2;
  } else if (frameAspect < containerAspect) {
    innerW = (frameAspect / containerAspect) * 100;
    innerLeft = (100 - innerW) / 2;
  }

  return (
    <div
      className={`absolute z-[5] pointer-events-none transition-opacity duration-500 ${faded ? "opacity-0" : "opacity-100"}`}
      style={{ left: `${innerLeft}%`, top: `${innerTop}%`, width: `${innerW}%`, height: `${innerH}%` }}
    >
      {detections.map((det, i) => {
        const [x1, y1, x2, y2] = det.bbox;
        const left = (x1 / frameWidth) * 100;
        const top = (y1 / frameHeight) * 100;
        const width = ((x2 - x1) / frameWidth) * 100;
        const height = ((y2 - y1) / frameHeight) * 100;

        return (
          <div key={`${det.label}-${i}`} style={{
            position: "absolute",
            left: `${left}%`,
            top: `${top}%`,
            width: `${width}%`,
            height: `${height}%`,
            border: `2px solid ${det.borderColor}`,
            backgroundColor: det.color,
            borderRadius: "2px",
          }}>
            <span style={{
              position: "absolute",
              top: "-18px",
              left: "0",
              fontSize: "10px",
              lineHeight: "16px",
              padding: "0 4px",
              backgroundColor: det.borderColor,
              color: "#000",
              borderRadius: "2px",
              whiteSpace: "nowrap",
              fontWeight: 600,
            }}>
              {det.label}
            </span>
          </div>
        );
      })}
      {hasSkeletons && (
        <svg
          viewBox={`0 0 ${skeletons!.width} ${skeletons!.height}`}
          preserveAspectRatio="none"
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
        >
          {skeletons!.people.map((p, pi) => {
            const kp = p.keypoints || [];
            const ok = (i: number) => kp[i] && (kp[i][2] ?? 1) > 0.3;
            return (
              <g key={pi} stroke="rgb(34,211,238)" strokeWidth={Math.max(2, skeletons!.width / 480)} fill="rgb(34,211,238)">
                {COCO_EDGES.map(([a, b], ei) =>
                  ok(a) && ok(b) ? (
                    <line key={ei} x1={kp[a][0]} y1={kp[a][1]} x2={kp[b][0]} y2={kp[b][1]} opacity={0.85} />
                  ) : null
                )}
                {kp.map((pt, ki) =>
                  ok(ki) ? <circle key={ki} cx={pt[0]} cy={pt[1]} r={Math.max(3, skeletons!.width / 400)} opacity={0.9} /> : null
                )}
                {p.bbox && p.action && p.action !== "unknown" && (
                  <text x={p.bbox[0]} y={Math.max(14, p.bbox[1] - 8)}
                    fontSize={Math.max(12, skeletons!.width / 80)} fill="rgb(34,211,238)" stroke="none" fontWeight="600">
                    {(p.person_name ? `${p.person_name} · ` : "") + p.action.replace(/_/g, " ")}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

// ── Mini PTZ hover control ──

export function MiniPTZ({ cameraId, onClose }: { cameraId: string; onClose: () => void }) {
  const { authFetch } = useAuth();
  const holdRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const send = useCallback(async (pan: number, tilt: number, zoom: number) => {
    try {
      await authFetch(`/api/cameras/${cameraId}/ptz/move`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pan, tilt, zoom }),
      });
    } catch { /* silent */ }
  }, [authFetch, cameraId]);

  const stop = useCallback(async () => {
    try { await authFetch(`/api/cameras/${cameraId}/ptz/stop`, { method: "POST" }); } catch { /* silent */ }
  }, [authFetch, cameraId]);

  const startHold = useCallback((pan: number, tilt: number, zoom: number) => {
    send(pan, tilt, zoom);
    holdRef.current = setInterval(() => send(pan, tilt, zoom), 250);
  }, [send]);

  const stopHold = useCallback(() => {
    if (holdRef.current) { clearInterval(holdRef.current); holdRef.current = null; }
    stop();
  }, [stop]);

  useEffect(() => () => { if (holdRef.current) clearInterval(holdRef.current); }, []);

  const SPD = 0.5;
  const ZSPD = 0.5;
  const arrowBtn =
    "w-7 h-7 flex items-center justify-center rounded-sm bg-white/10 hover:bg-white/25 text-white/90 text-xs border border-white/10 transition-colors select-none";

  const mk = (pan: number, tilt: number, zoom: number, label: string) => ({
    "aria-label": label,
    title: label,
    onMouseDown: (e: React.MouseEvent) => { e.stopPropagation(); startHold(pan, tilt, zoom); },
    onMouseUp: (e: React.MouseEvent) => { e.stopPropagation(); stopHold(); },
    onMouseLeave: () => { if (holdRef.current) stopHold(); },
    onTouchStart: (e: React.TouchEvent) => { e.stopPropagation(); startHold(pan, tilt, zoom); },
    onTouchEnd: (e: React.TouchEvent) => { e.stopPropagation(); stopHold(); },
  });

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      className="absolute bottom-10 right-1.5 z-20 rounded-md bg-black/80 backdrop-blur-sm border border-white/15 p-1.5 shadow-lg"
    >
      <div className="flex items-center gap-2">
        {/* Direction pad */}
        <div className="grid grid-cols-3 grid-rows-3 gap-0.5 w-[5.5rem]">
          <span />
          <button {...mk(0, SPD, 0, "Tilt up")} className={arrowBtn}>↑</button>
          <span />
          <button {...mk(-SPD, 0, 0, "Pan left")} className={arrowBtn}>←</button>
          <button onClick={(e) => { e.stopPropagation(); stop(); }} className={arrowBtn + " opacity-60"} aria-label="Stop movement" title="Stop">■</button>
          <button {...mk(SPD, 0, 0, "Pan right")} className={arrowBtn}>→</button>
          <span />
          <button {...mk(0, -SPD, 0, "Tilt down")} className={arrowBtn}>↓</button>
          <span />
        </div>
        {/* Zoom */}
        <div className="flex flex-col gap-0.5">
          <button {...mk(0, 0, ZSPD, "Zoom in")} className={arrowBtn}>+</button>
          <button {...mk(0, 0, -ZSPD, "Zoom out")} className={arrowBtn}>−</button>
          <button onClick={(e) => { e.stopPropagation(); onClose(); }} className={arrowBtn + " opacity-60"} aria-label="Close PTZ controls" title="Close">×</button>
        </div>
      </div>
    </div>
  );
}


