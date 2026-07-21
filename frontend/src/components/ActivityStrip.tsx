"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { RecordingModal } from "@/components/RecordingModal";
import { formatWith } from "@/lib/time";

// A scrubber for one camera with an activity heatmap drawn over it.
//
// Two layers, deliberately:
//   - the *track* is what footage exists. Solid where a recording covers the
//     time, dead where it does not, so you can see what is clickable before
//     clicking. Recording is motion-triggered, so footage comes in islands.
//   - the *heatmap* is a continuous intensity curve over that track: how much
//     movement (blue) and how much human presence (green) at each moment.
//     Curves rather than blocks, so a peak or a quiet stretch reads at a glance.
//
// Clicking anywhere seeks into the recording covering that moment, at that
// moment, rather than restarting the clip.

interface Bucket {
  t: string;
  motion: number; // 0..1 raw movement
  person: number; // 0..1 human presence
  person_ids: string[];
}
interface StripPerson {
  id: string;
  name: string | null;
  first_seen: string;
  last_seen: string;
}
interface StripRec {
  id: string;
  started_at: string;
  ended_at: string | null;
}
interface StripData {
  start: string;
  end: string;
  hours: number;
  buckets: Bucket[];
  persons: StripPerson[];
  recordings: StripRec[];
}

const HOURS_OPTIONS = [1, 3, 12, 24];
const ASSUMED_CLIP_MS = 300000; // when a recording has no ended_at yet

function fmtClock(iso: string | number): string {
  try {
    return formatWith(new Date(iso), { hour: "numeric", minute: "2-digit" });
  } catch {
    return "";
  }
}

/** Area path across the full width for a 0..1 series, in a `h`-tall viewBox. */
function areaPath(values: number[], h: number): string {
  const n = values.length;
  if (n < 2) return "";
  const pts = values.map((v, i) => {
    const x = (i / (n - 1)) * 100;
    const y = h - Math.max(0, Math.min(1, v)) * h;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  return `M0,${h} L${pts.join(" L")} L100,${h} Z`;
}

export function ActivityStrip({
  cameraId,
  cameraName,
  variant = "full",
  hours: fixedHours,
}: {
  cameraId: string;
  cameraName?: string | null;
  variant?: "full" | "compact";
  hours?: number;
}) {
  const { authFetch, token } = useAuth();
  const compact = variant === "compact";
  const [hours, setHours] = useState(fixedHours ?? 3);
  const [data, setData] = useState<StripData | null>(null);
  const [open, setOpen] = useState<{ rec: StripRec; seekTo: string } | null>(null);
  const [hoverPct, setHoverPct] = useState<number | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const trackRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch(
        `/api/cameras/${cameraId}/activity-strip?hours=${hours}&buckets=${compact ? 80 : 120}`
      );
      if (res.ok) setData(await res.json());
    } catch {
      /* keep last */
    }
  }, [authFetch, cameraId, hours, compact]);

  useEffect(() => {
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, [load]);

  const personById = useMemo(() => {
    const m: Record<string, StripPerson> = {};
    data?.persons.forEach((p) => (m[p.id] = p));
    return m;
  }, [data]);

  const startMs = data ? new Date(data.start).getTime() : 0;
  const endMs = data ? new Date(data.end).getTime() : 1;
  const spanMs = endMs - startMs || 1;
  const pctOf = (iso: string) =>
    Math.min(100, Math.max(0, ((new Date(iso).getTime() - startMs) / spanMs) * 100));
  const timeAtPct = (pct: number) => startMs + (pct / 100) * spanMs;

  // Where footage actually exists, as %-of-window spans. Clipped to the window
  // at BOTH edges: a clip that began before the window must not be drawn for
  // its full duration, or the bar overhangs past its real end and those pixels
  // look clickable while matching no recording.
  const coverage = useMemo(() => {
    if (!data) return [];
    return data.recordings
      .map((r) => {
        const rs = new Date(r.started_at).getTime();
        const re = r.ended_at ? new Date(r.ended_at).getTime() : rs + ASSUMED_CLIP_MS;
        const vs = Math.max(rs, startMs);
        const ve = Math.min(re, endMs);
        return {
          rec: r,
          left: ((vs - startMs) / spanMs) * 100,
          width: ((ve - vs) / spanMs) * 100,
          visible: ve > vs,
        };
      })
      .filter((c) => c.visible);
  }, [data, startMs, endMs, spanMs]);

  /** The clip covering `ms`, else the nearest one within a small tolerance.
   *
   * Clips are short (median ~14s) against a multi-hour window, so an exact hit
   * would demand sub-pixel accuracy. Snapping to the nearest clip keeps every
   * drawn segment reachable. Returns the clip and the moment to open it at,
   * clamped inside the clip so the seek is always valid. */
  const clipFor = (ms: number): { rec: StripRec; seekMs: number } | null => {
    if (!data) return null;
    const tolerance = spanMs * 0.01; // 1% of the window
    let best: { rec: StripRec; seekMs: number; distance: number } | null = null;
    for (const r of data.recordings) {
      const rs = new Date(r.started_at).getTime();
      const re = r.ended_at ? new Date(r.ended_at).getTime() : rs + ASSUMED_CLIP_MS;
      const distance = ms < rs ? rs - ms : ms > re ? ms - re : 0;
      if (distance > tolerance) continue;
      if (!best || distance < best.distance) {
        // Inside the clip: open at the exact moment. Snapped from outside:
        // open at the clip's start, never its nearest edge -- clamping to the
        // end lands on the final frame and playback finishes instantly.
        best = { rec: r, seekMs: distance === 0 ? ms : rs, distance };
      }
      if (distance === 0) break;
    }
    return best ? { rec: best.rec, seekMs: best.seekMs } : null;
  };

  const bucketAtPct = (pct: number): Bucket | null => {
    if (!data?.buckets.length) return null;
    const i = Math.min(
      data.buckets.length - 1,
      Math.max(0, Math.round((pct / 100) * (data.buckets.length - 1)))
    );
    return data.buckets[i];
  };

  const pctFromEvent = (e: React.MouseEvent) => {
    const el = trackRef.current;
    if (!el) return 0;
    const r = el.getBoundingClientRect();
    return Math.min(100, Math.max(0, ((e.clientX - r.left) / r.width) * 100));
  };

  const onClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    const pct = pctFromEvent(e);
    const ms = timeAtPct(pct);
    const hit = clipFor(ms);
    if (!hit) {
      // Motion-triggered recording leaves gaps. Say so rather than no-op.
      setNote(`No footage at ${fmtClock(ms)}`);
      setTimeout(() => setNote(null), 1800);
      return;
    }
    setOpen({ rec: hit.rec, seekTo: new Date(hit.seekMs).toISOString() });
  };

  const h = compact ? 26 : 44;
  const motionPath = data ? areaPath(data.buckets.map((b) => b.motion), h) : "";
  const personPath = data ? areaPath(data.buckets.map((b) => b.person), h) : "";
  const hoverBucket = hoverPct != null ? bucketAtPct(hoverPct) : null;
  const hoverMs = hoverPct != null ? timeAtPct(hoverPct) : null;
  const hoverHasFootage = hoverMs != null && !!clipFor(hoverMs);
  const hasAny = !!data && data.buckets.some((b) => b.motion > 0 || b.person > 0);

  const scrubber = (
    <div
      ref={trackRef}
      className="relative w-full cursor-pointer select-none"
      style={{ height: h }}
      onMouseMove={(e) => setHoverPct(pctFromEvent(e))}
      onMouseLeave={() => setHoverPct(null)}
      onClick={onClick}
    >
      {/* Track: dead by default, lit where footage exists. */}
      <div className="absolute inset-0 rounded bg-black/50 overflow-hidden">
        {coverage.map((c, i) => (
          <div
            key={`${c.rec.id}-${i}`}
            className="absolute inset-y-0 bg-white/10"
            style={{ left: `${c.left}%`, width: `${Math.max(c.width, 0.3)}%` }}
          />
        ))}
      </div>

      {/* Heatmap curves over the track. */}
      <svg
        viewBox={`0 0 100 ${h}`}
        preserveAspectRatio="none"
        className="absolute inset-0 w-full h-full pointer-events-none rounded overflow-hidden"
      >
        {motionPath && <path d={motionPath} fill="rgba(56,189,248,0.45)" />}
        {personPath && <path d={personPath} fill="rgba(34,197,94,0.65)" />}
      </svg>

      {/* Hover position line, YouTube-style. */}
      {hoverPct != null && (
        <div
          className={`absolute top-0 bottom-0 w-px pointer-events-none ${
            hoverHasFootage ? "bg-white/80" : "bg-white/25"
          }`}
          style={{ left: `${hoverPct}%` }}
        />
      )}

      {!hasAny && (
        <div className="absolute inset-0 flex items-center justify-center text-[9px] text-muted-foreground pointer-events-none">
          No activity in the last {hours}h
        </div>
      )}
    </div>
  );

  const tooltip =
    hoverPct != null && hoverBucket && hoverMs != null ? (
      <div
        className="absolute -top-1 -translate-x-1/2 -translate-y-full z-30 whitespace-nowrap px-2 py-1 rounded bg-popover border border-border text-[10px] shadow-lg pointer-events-none"
        style={{ left: `${hoverPct}%` }}
      >
        <span className="font-mono">{fmtClock(hoverMs)}</span>
        {hoverBucket.person_ids.length > 0 && (
          <span className="ml-1.5 text-green-400">
            {hoverBucket.person_ids.map((id) => personById[id]?.name || "Unknown").join(", ")}
          </span>
        )}
        {hoverBucket.person_ids.length === 0 && hoverBucket.motion > 0 && (
          <span className="ml-1.5 text-sky-400">movement</span>
        )}
        <span className="ml-1.5 text-muted-foreground">
          {hoverHasFootage ? "· click to play" : "· no footage"}
        </span>
      </div>
    ) : null;

  const faces = (size: string) => (
    <div className={`relative ${compact ? "h-5" : "h-8"} mb-0.5`}>
      {data?.persons.map((p) => (
        <div
          key={p.id}
          className="absolute -translate-x-1/2"
          style={{ left: `${pctOf(p.first_seen)}%` }}
          title={`${p.name || "Unknown"} · ${fmtClock(p.first_seen)}–${fmtClock(p.last_seen)}`}
        >
          {p.name ? (
            <img
              src={`/api/persons/${p.id}/photo${token ? `?token=${token}` : ""}`}
              alt={p.name}
              className={`${size} rounded-full object-cover border border-green-500/80 bg-muted`}
              onError={(e) => ((e.currentTarget as HTMLImageElement).style.visibility = "hidden")}
            />
          ) : (
            <div className={`${size} rounded-full border border-yellow-500/80 bg-muted`} />
          )}
        </div>
      ))}
    </div>
  );

  const modal = open && (
    <RecordingModal
      recording={{ ...open.rec, camera_id: cameraId }}
      cameraName={cameraName}
      seekTo={open.seekTo}
      onClose={() => setOpen(null)}
    />
  );

  if (compact) {
    return (
      <div className="w-full px-1.5 pb-1 relative" onClick={(e) => e.stopPropagation()}>
        {faces("w-5 h-5")}
        <div className="relative">
          {scrubber}
          {tooltip}
        </div>
        {note && (
          <div className="absolute inset-x-0 -bottom-1 text-center text-[9px] text-muted-foreground">
            {note}
          </div>
        )}
        {modal}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card/50 p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          Activity
        </span>
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 text-[9px] text-muted-foreground">
            <span className="w-2 h-2 rounded-sm bg-sky-400/70" /> movement
            <span className="w-2 h-2 rounded-sm bg-green-500/80 ml-1.5" /> person
            <span className="w-2 h-2 rounded-sm bg-white/10 ml-1.5" /> footage
          </span>
          <div className="flex items-center gap-1">
            {HOURS_OPTIONS.map((x) => (
              <button
                key={x}
                onClick={() => setHours(x)}
                className={`px-1.5 py-0.5 text-[10px] rounded transition-colors ${
                  hours === x
                    ? "bg-accent/15 text-accent-foreground border border-accent/30"
                    : "text-muted-foreground border border-transparent hover:bg-muted"
                }`}
              >
                {x}h
              </button>
            ))}
          </div>
        </div>
      </div>
      {faces("w-7 h-7")}
      <div className="relative">
        {scrubber}
        {tooltip}
      </div>
      <div className="flex justify-between mt-1 text-[9px] text-muted-foreground font-mono">
        <span>{data ? fmtClock(data.start) : ""}</span>
        <span>{note || (data ? fmtClock(data.end) : "now")}</span>
      </div>
      {modal}
    </div>
  );
}
