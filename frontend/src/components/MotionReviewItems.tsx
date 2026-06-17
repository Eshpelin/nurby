"use client";

// Motion-only review items for a recording: contiguous spans of significant
// motion that the object detector found NOTHING in (GET
// /api/cameras/{id}/motion/review-items). These catch activity the detector
// missed, complementing the detection-jump controls. Each span renders as a
// click-to-seek row that jumps the shared <video> to the span's start, reusing
// the same currentTime seek the heatstrip and detection controls use.
//
// Motion persistence is gated behind an admin flag (motion_series_enabled,
// default off), so this endpoint legitimately returns zero items on most
// installs. In that case the whole panel hides itself (no header, no error, no
// console spam) so it never reads as broken on a vanilla setup.

import { useEffect, useMemo, useState, type RefObject } from "react";
import { useAuth } from "@/lib/auth";

interface ReviewItem {
  start: string; // ISO span start
  end: string; // ISO span end (half-open)
  duration_seconds: number;
  peak_intensity: number; // 0..1
  samples: number;
}

interface ReviewItemsResponse {
  items: ReviewItem[];
  count: number;
}

// Cap the rendered rows so a busy window can't produce an unwieldy list. The
// endpoint itself bounds the span count (MAX_REVIEW_SPANS); this just keeps the
// inline panel compact, with a count of any overflow.
const MAX_ROWS = 50;

function formatOffset(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r === 0 ? `${m}m` : `${m}m ${r}s`;
}

export function MotionReviewItems({
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
  const [items, setItems] = useState<ReviewItem[]>([]);

  const base = useMemo(() => new Date(startedAt).getTime(), [startedAt]);
  // Clip span in seconds: explicit duration, else end - start, else a 1h
  // fallback so an in-progress clip with no end still maps cleanly. Mirrors
  // the MotionHeatstrip window so both surfaces query the same range.
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
      try {
        const res = await authFetch(
          `/api/cameras/${cameraId}/motion/review-items` +
            `?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`,
        );
        // Non-OK (incl. 422 on a degenerate window) degrades to no items.
        if (!res.ok || cancelled) return;
        const data = (await res.json()) as ReviewItemsResponse;
        if (cancelled) return;
        setItems(Array.isArray(data.items) ? data.items : []);
      } catch {
        /* offline / aborted: leave the panel empty, no console spam */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [cameraId, startedAt, base, spanSeconds, authFetch]);

  // Map each span onto a playback offset (seconds from clip start), keeping
  // only those that land inside the clip. Sorted by the endpoint already.
  const rows = useMemo(() => {
    if (spanSeconds <= 0) return [];
    return items
      .map((it) => {
        const offset = (new Date(it.start).getTime() - base) / 1000;
        return {
          offset,
          duration: it.duration_seconds,
          intensity: Math.max(0, Math.min(1, it.peak_intensity)),
        };
      })
      .filter((r) => r.offset >= 0 && r.offset < spanSeconds);
  }, [items, base, spanSeconds]);

  // Seek the shared <video> to a clip offset. Prefer the real media duration
  // when known (decoded length can differ slightly from the recorded span),
  // scaling the offset across it, exactly as the heatstrip does.
  const seekToOffset = (offset: number) => {
    const v = videoRef.current;
    if (!v) return;
    const dur =
      Number.isFinite(v.duration) && v.duration > 0 ? v.duration : spanSeconds;
    const clamped = Math.max(0, Math.min(dur, (offset / spanSeconds) * dur));
    v.currentTime = clamped;
    v.play?.().catch(() => undefined);
  };

  // Gated flag off / empty series / no motion-only spans: render nothing so the
  // panel never appears on a vanilla install.
  if (rows.length === 0) return null;

  const shown = rows.slice(0, MAX_ROWS);
  const overflow = rows.length - shown.length;

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-mono">
          Review &middot; motion, no detection
        </span>
        <span className="text-[10px] text-muted-foreground/70">
          {rows.length} span{rows.length === 1 ? "" : "s"}
        </span>
      </div>
      <ul className="max-h-32 overflow-y-auto rounded border border-border bg-[hsl(0_0%_8%)] divide-y divide-border/60">
        {shown.map((r, i) => (
          <li key={i}>
            <button
              type="button"
              onClick={() => seekToOffset(r.offset)}
              title="Jump to this unreviewed motion"
              className="flex w-full items-center gap-3 px-2.5 py-1.5 text-left text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors focus:outline-none focus:bg-muted focus:text-foreground"
            >
              {/* Intensity pip: brighter for stronger peak motion. */}
              <span
                aria-hidden
                className="h-2 w-2 shrink-0 rounded-full bg-accent"
                style={{ opacity: 0.3 + r.intensity * 0.7 }}
              />
              <span className="font-mono tabular-nums">{formatOffset(r.offset)}</span>
              <span className="text-muted-foreground/60">
                {formatDuration(r.duration)}
              </span>
            </button>
          </li>
        ))}
        {overflow > 0 && (
          <li className="px-2.5 py-1.5 text-[11px] text-muted-foreground/60">
            +{overflow} more
          </li>
        )}
      </ul>
    </div>
  );
}
