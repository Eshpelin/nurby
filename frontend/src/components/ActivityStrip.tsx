"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/lib/auth";
import { RecordingModal } from "@/components/RecordingModal";
import { formatWith } from "@/lib/time";

// A seeker for one camera: when movement happened, when a *person* was there,
// and who. Two channels are drawn in one strip because they answer different
// questions -- a blue wash means the camera saw something (pet, headlights,
// shadow), a green mark means a human was actually there. Faces sit at the time
// they first appeared. Clicking scrubs into the recording covering that moment,
// so you can skip straight to what matters instead of scrubbing hours.
//
// `compact` is the always-on bar pinned under each video tile on the wall;
// `full` adds the window selector, a faces row and a time axis for the camera
// detail page.

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

function fmtClock(iso: string): string {
  try {
    return formatWith(new Date(iso), { hour: "numeric", minute: "2-digit" });
  } catch {
    return "";
  }
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
  const [hours, setHours] = useState(fixedHours ?? (compact ? 3 : 3));
  const [data, setData] = useState<StripData | null>(null);
  const [openRec, setOpenRec] = useState<(StripRec & { camera_id: string }) | null>(null);
  const [hover, setHover] = useState<{ index: number; leftPct: number } | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch(
        `/api/cameras/${cameraId}/activity-strip?hours=${hours}&buckets=${compact ? 60 : 90}`
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

  const hasAny =
    !!data && data.buckets.some((b) => b.motion > 0 || b.person > 0);

  // The bar itself: motion as a blue wash behind, human presence as a solid
  // green bar in front, so the two read apart at a glance.
  const bar = (
    <div
      className={`relative flex ${compact ? "h-4" : "h-9"} rounded overflow-hidden bg-black/40 cursor-pointer`}
      onMouseLeave={() => setHover(null)}
    >
      {data?.buckets.map((b, i) => (
        <div
          key={b.t}
          className="relative flex-1 h-full hover:brightness-150"
          onMouseEnter={() =>
            setHover({ index: i, leftPct: (i / (data.buckets.length - 1 || 1)) * 100 })
          }
          onClick={(e) => {
            e.stopPropagation();
            openCovering(b.t);
          }}
        >
          {b.motion > 0 && (
            <div
              className="absolute inset-0"
              style={{ backgroundColor: `rgba(56,189,248,${0.15 + b.motion * 0.5})` }}
            />
          )}
          {b.person > 0 && (
            <div
              className="absolute inset-x-0 bottom-0"
              style={{
                height: `${Math.max(25, b.person * 100)}%`,
                backgroundColor: `rgba(34,197,94,${0.55 + b.person * 0.45})`,
              }}
            />
          )}
        </div>
      ))}
      {!hasAny && (
        <div className="absolute inset-0 flex items-center justify-center text-[9px] text-muted-foreground">
          No activity in the last {hours}h
        </div>
      )}
      {hover && data && (
        <div
          className="absolute -top-8 -translate-x-1/2 z-20 whitespace-nowrap px-2 py-1 rounded bg-popover border border-border text-[10px] shadow-lg pointer-events-none"
          style={{ left: `${hover.leftPct}%` }}
        >
          <span className="font-mono">{fmtClock(data.buckets[hover.index].t)}</span>
          {data.buckets[hover.index].person_ids.length > 0 ? (
            <span className="ml-1 text-green-400">
              {data.buckets[hover.index].person_ids
                .map((id) => personById[id]?.name || "Unknown")
                .join(", ")}
            </span>
          ) : data.buckets[hover.index].motion > 0 ? (
            <span className="ml-1 text-sky-400">movement</span>
          ) : null}
        </div>
      )}
    </div>
  );

  // Faces pinned at when each person first appeared.
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

  if (compact) {
    return (
      <div className="w-full px-1.5 pb-1" onClick={(e) => e.stopPropagation()}>
        {faces("w-5 h-5")}
        {bar}
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
      </div>
      {faces("w-7 h-7")}
      {bar}
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
