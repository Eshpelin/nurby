"use client";

// A horizontal motion-activity heatstrip aligned to a recording's <video>
// playback axis. Fetches the server-side-bucketed motion series for the clip's
// [from, to] window (GET /api/cameras/{id}/motion) and paints each bucket as a
// segment whose brightness tracks the peak motion intensity (0..1) in that
// slice of time. Clicking anywhere on the strip seeks the shared <video> to the
// matching playback offset, reusing the same currentTime seek the rest of the
// recordings UI uses.
//
// Motion persistence is gated behind an admin flag (motion_series_enabled,
// default off), so the endpoint legitimately returns zero buckets on most
// installs. In that case the strip renders flat (no error, no console spam) so
// it reads as "no motion data" rather than broken.

import { useEffect, useMemo, useState, type RefObject } from "react";
import { useAuth } from "@/lib/auth";

interface MotionBucket {
  t: string; // ISO bucket start
  intensity: number; // peak score in the bucket, 0..1
  samples: number;
}

interface MotionResponse {
  bucket_seconds: number;
  buckets: MotionBucket[];
  count: number;
}

// Target roughly this many buckets across the whole clip, so the request stays
// compact and each segment is a comfortable few pixels wide. The endpoint
// clamps bucket_seconds into [1, 3600] itself; we only pick a sensible width.
const TARGET_BUCKETS = 120;

export function MotionHeatstrip({
  cameraId,
  startedAt,
  endedAt,
  durationSeconds,
  videoRef,
}: {
  cameraId: string;
  startedAt: string;
  endedAt?: string | null;
  durationSeconds?: number | null;
  videoRef: RefObject<HTMLVideoElement | null>;
}) {
  const { authFetch } = useAuth();
  const [buckets, setBuckets] = useState<MotionBucket[]>([]);
  const [bucketSeconds, setBucketSeconds] = useState(0);
  const [t, setT] = useState(0); // playhead, seconds from clip start

  // Clip span in seconds, from the explicit duration, else end - start, else a
  // 1h fallback so an in-progress clip with no end still maps cleanly.
  const base = useMemo(() => new Date(startedAt).getTime(), [startedAt]);
  const spanSeconds = useMemo(() => {
    if (durationSeconds && durationSeconds > 0) return durationSeconds;
    if (endedAt) {
      const s = (new Date(endedAt).getTime() - base) / 1000;
      if (s > 0) return s;
    }
    return 3600;
  }, [durationSeconds, endedAt, base]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const from = startedAt;
      const to = new Date(base + spanSeconds * 1000).toISOString();
      // Width that yields ~TARGET_BUCKETS slices; at least 1s (the write
      // resolution), and the endpoint clamps the upper bound.
      const width = Math.max(1, Math.round(spanSeconds / TARGET_BUCKETS));
      try {
        const res = await authFetch(
          `/api/cameras/${cameraId}/motion?from=${encodeURIComponent(from)}` +
            `&to=${encodeURIComponent(to)}&bucket_seconds=${width}`,
        );
        // Non-OK (incl. 422 on a degenerate window) degrades to a flat strip.
        if (!res.ok || cancelled) return;
        const data = (await res.json()) as MotionResponse;
        if (cancelled) return;
        setBuckets(Array.isArray(data.buckets) ? data.buckets : []);
        setBucketSeconds(data.bucket_seconds || width);
      } catch {
        /* offline / aborted: leave the strip flat, no console spam */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [cameraId, startedAt, base, spanSeconds, authFetch]);

  // Mirror the <video> playhead so the strip shows where playback currently is.
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onTime = () => setT(v.currentTime);
    onTime();
    v.addEventListener("timeupdate", onTime);
    v.addEventListener("seeked", onTime);
    return () => {
      v.removeEventListener("timeupdate", onTime);
      v.removeEventListener("seeked", onTime);
    };
  }, [videoRef]);

  // Pre-position each bucket as a left/width % of the clip span, dropping any
  // that fall outside [0, span] (clock skew / partial first-second buckets).
  const segments = useMemo(() => {
    if (bucketSeconds <= 0 || spanSeconds <= 0) return [];
    return buckets
      .map((b) => {
        const offset = (new Date(b.t).getTime() - base) / 1000;
        return {
          leftPct: (offset / spanSeconds) * 100,
          widthPct: (bucketSeconds / spanSeconds) * 100,
          intensity: Math.max(0, Math.min(1, b.intensity)),
        };
      })
      .filter((s) => s.leftPct < 100 && s.leftPct + s.widthPct > 0);
  }, [buckets, bucketSeconds, base, spanSeconds]);

  const hasMotion = segments.length > 0;
  const playheadPct = spanSeconds > 0
    ? Math.max(0, Math.min(100, (t / spanSeconds) * 100))
    : 0;

  // Map a click x-fraction onto a playback offset and seek the shared <video>.
  const seekToFraction = (frac: number) => {
    const v = videoRef.current;
    if (!v) return;
    const clamped = Math.max(0, Math.min(1, frac));
    // Prefer the real media duration when known (handles clips whose decoded
    // length differs slightly from the recorded span); else use the span.
    const dur = Number.isFinite(v.duration) && v.duration > 0 ? v.duration : spanSeconds;
    v.currentTime = clamped * dur;
    v.play?.().catch(() => undefined);
  };

  const onClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return;
    seekToFraction((e.clientX - rect.left) / rect.width);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const v = videoRef.current;
    if (!v) return;
    const dur = Number.isFinite(v.duration) && v.duration > 0 ? v.duration : spanSeconds;
    if (e.key === "ArrowRight") {
      e.preventDefault();
      seekToFraction((v.currentTime + dur / TARGET_BUCKETS) / dur);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      seekToFraction((v.currentTime - dur / TARGET_BUCKETS) / dur);
    }
  };

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-mono">
          Motion
        </span>
        {!hasMotion && (
          <span className="text-[10px] text-muted-foreground/70">
            No motion data
          </span>
        )}
      </div>
      <div
        role="slider"
        tabIndex={0}
        aria-label="Motion activity. Click or use arrow keys to seek playback."
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(playheadPct)}
        onClick={onClick}
        onKeyDown={onKeyDown}
        className="relative h-6 w-full cursor-pointer overflow-hidden rounded border border-border bg-[hsl(0_0%_8%)] focus:outline-none focus:ring-1 focus:ring-accent"
        title={hasMotion ? "Click to seek to this moment" : "Motion activity will appear here once it is enabled"}
      >
        {segments.map((s, i) => (
          <div
            key={i}
            className="absolute inset-y-0 bg-accent"
            style={{
              left: `${s.leftPct}%`,
              width: `${s.widthPct}%`,
              // Floor opacity so even faint motion is visible, then scale up.
              opacity: 0.15 + s.intensity * 0.85,
            }}
          />
        ))}
        {/* Playhead marker, tracks the shared <video> currentTime. */}
        <div
          className="absolute inset-y-0 w-px bg-foreground/90 pointer-events-none"
          style={{ left: `${playheadPct}%` }}
        />
      </div>
    </div>
  );
}
