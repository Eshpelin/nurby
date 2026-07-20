"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/lib/auth";
import { RecordingModal } from "@/components/RecordingModal";

// A presence + movement timeline for one camera: a heatmap of when activity
// happened plus the faces of who was present, so you can scrub straight to the
// interesting moments instead of scrubbing through hours of footage. Clicking a
// slot opens the recording that covers it.

interface Bucket {
  t: string;
  activity: number; // 0..1
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

function fmtClock(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  } catch {
    return "";
  }
}

function activityColor(a: number): string {
  if (a <= 0) return "transparent";
  // low -> muted green, high -> amber, so busy stretches stand out.
  if (a < 0.34) return `rgba(34,197,94,${0.25 + a})`;
  if (a < 0.67) return `rgba(132,204,22,${0.35 + a * 0.5})`;
  return `rgba(245,158,11,${0.5 + a * 0.4})`;
}

export function ActivityStrip({
  cameraId,
  cameraName,
}: {
  cameraId: string;
  cameraName?: string | null;
}) {
  const { authFetch, token } = useAuth();
  const [hours, setHours] = useState(3);
  const [data, setData] = useState<StripData | null>(null);
  const [openRec, setOpenRec] = useState<StripRec & { camera_id: string } | null>(null);
  const [hover, setHover] = useState<{ index: number; leftPct: number } | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch(`/api/cameras/${cameraId}/activity-strip?hours=${hours}`);
      if (res.ok) setData(await res.json());
    } catch {
      /* keep last */
    }
  }, [authFetch, cameraId, hours]);

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
  const spanMs = data ? new Date(data.end).getTime() - startMs || 1 : 1;
  const pctOf = (iso: string) =>
    Math.min(100, Math.max(0, ((new Date(iso).getTime() - startMs) / spanMs) * 100));

  const openCovering = (iso: string) => {
    const t = new Date(iso).getTime();
    const rec = data?.recordings.find((r) => {
      const rs = new Date(r.started_at).getTime();
      const re = r.ended_at ? new Date(r.ended_at).getTime() : rs + 300000;
      return t >= rs && t <= re;
    });
    if (rec) setOpenRec({ ...rec, camera_id: cameraId });
  };

  const hasAny = !!data && data.buckets.some((b) => b.activity > 0);

  return (
    <div className="rounded-lg border border-border bg-card/50 p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          Activity
        </span>
        <div className="flex items-center gap-1">
          {HOURS_OPTIONS.map((h) => (
            <button
              key={h}
              onClick={() => setHours(h)}
              className={`px-1.5 py-0.5 text-[10px] rounded transition-colors ${
                hours === h
                  ? "bg-accent/15 text-accent-foreground border border-accent/30"
                  : "text-muted-foreground border border-transparent hover:bg-muted"
              }`}
            >
              {h}h
            </button>
          ))}
        </div>
      </div>

      {/* Faces present in this window, placed at when they first appeared. */}
      <div className="relative h-8 mb-1">
        {data?.persons.map((p) => (
          <div
            key={p.id}
            className="absolute -translate-x-1/2 group"
            style={{ left: `${pctOf(p.first_seen)}%` }}
            title={`${p.name || "Unknown"} · ${fmtClock(p.first_seen)}–${fmtClock(p.last_seen)}`}
          >
            {p.name ? (
              <img
                src={`/api/persons/${p.id}/photo${token ? `?token=${token}` : ""}`}
                alt={p.name}
                className="w-7 h-7 rounded-full object-cover border-2 border-green-500/70 bg-muted"
                onError={(e) => ((e.currentTarget as HTMLImageElement).style.visibility = "hidden")}
              />
            ) : (
              <div className="w-7 h-7 rounded-full border-2 border-yellow-500/70 bg-muted" />
            )}
          </div>
        ))}
      </div>

      {/* Heatmap of activity across the window. */}
      <div
        className="relative flex h-9 rounded overflow-hidden bg-muted/30 cursor-pointer"
        onMouseLeave={() => setHover(null)}
      >
        {data?.buckets.map((b, i) => (
          <div
            key={b.t}
            className="flex-1 h-full hover:brightness-125"
            style={{ backgroundColor: activityColor(b.activity) }}
            onMouseEnter={() => setHover({ index: i, leftPct: (i / (data.buckets.length - 1 || 1)) * 100 })}
            onClick={() => openCovering(b.t)}
          />
        ))}
        {!hasAny && (
          <div className="absolute inset-0 flex items-center justify-center text-[10px] text-muted-foreground">
            No activity in the last {hours}h
          </div>
        )}
        {hover && data && (
          <div
            className="absolute -top-9 -translate-x-1/2 z-10 whitespace-nowrap px-2 py-1 rounded bg-popover border border-border text-[10px] shadow-lg pointer-events-none"
            style={{ left: `${hover.leftPct}%` }}
          >
            <span className="font-mono">{fmtClock(data.buckets[hover.index].t)}</span>
            {data.buckets[hover.index].person_ids.length > 0 && (
              <span className="ml-1 text-green-400">
                {data.buckets[hover.index].person_ids
                  .map((id) => personById[id]?.name || "Unknown")
                  .join(", ")}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Time axis. */}
      <div className="flex justify-between mt-1 text-[9px] text-muted-foreground font-mono">
        <span>{data ? fmtClock(data.start) : ""}</span>
        <span>{data ? fmtClock(data.end) : "now"}</span>
      </div>

      {openRec && (
        <RecordingModal
          recording={openRec}
          cameraName={cameraName}
          onClose={() => setOpenRec(null)}
        />
      )}
    </div>
  );
}
