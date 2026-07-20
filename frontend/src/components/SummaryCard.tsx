"use client";

import { formatWith } from "@/lib/time";

interface PersonSeen {
  name: string;
  sightings: number;
  first_seen?: string;
  last_seen?: string;
}

interface SummaryCardProps {
  id: string;
  cameraId: string;
  cameraName?: string;
  kind: "periodic" | "event" | string;
  startedAt: string;
  endedAt: string;
  providerName?: string | null;
  triggerReason?: string;
  summaryText: string;
  peopleSeen?: PersonSeen[] | null;
  platesSeen?: string[] | null;
  objectCounts?: Record<string, number> | null;
}

const Sparkles = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" />
    <circle cx="12" cy="12" r="2" />
  </svg>
);

const ClockIcon = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <polyline points="12 6 12 12 16 14" />
  </svg>
);

/**
 * Timeline card for a window-level VLM summary. Distinct from
 * observation/transcript cards. Indigo/violet accent so the eye lands
 * on it as the "story" of a chunk of time.
 */
export function SummaryCard(props: SummaryCardProps) {
  const {
    cameraName,
    kind,
    startedAt,
    endedAt,
    providerName,
    triggerReason,
    summaryText,
    peopleSeen,
    platesSeen,
    objectCounts,
  } = props;

  const start = new Date(startedAt);
  const end = new Date(endedAt);
  const durationS = Math.max(1, Math.round((end.getTime() - start.getTime()) / 1000));
  const durationLabel =
    durationS < 60
      ? `${durationS}s`
      : durationS < 3600
        ? `${Math.round(durationS / 60)}m`
        : `${(durationS / 3600).toFixed(1)}h`;

  const topObjects = objectCounts
    ? Object.entries(objectCounts)
        .filter(([label]) => label !== "person")
        .sort((a, b) => b[1] - a[1])
        .slice(0, 4)
    : [];

  return (
    <div className="rounded-lg border border-indigo-500/40 bg-indigo-500/5 hover:border-indigo-400/60 transition overflow-hidden">
      <div className="px-3 py-2.5">
        <div className="flex items-center gap-2 text-[11px] mb-2">
          <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
          <span className="font-medium uppercase tracking-wider text-indigo-300">
            {kind === "event" ? "Event recap" : "Recap"}
          </span>
          <span className="text-muted-foreground">·</span>
          <span className="text-muted-foreground">{cameraName || "Camera"}</span>
          <span className="ml-auto flex items-center gap-1 text-muted-foreground">
            <ClockIcon className="w-3 h-3" />
            <span>
              {formatWith(start, { hour: "2-digit", minute: "2-digit" })}
              {" · "}
              {durationLabel}
            </span>
          </span>
        </div>

        <p className="text-sm text-foreground leading-relaxed">{summaryText}</p>

        {(peopleSeen?.length || platesSeen?.length || topObjects.length > 0 || providerName) && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {peopleSeen?.slice(0, 4).map((p) => (
              <span
                key={p.name}
                className="px-1.5 py-0.5 text-[10px] rounded bg-emerald-900/30 text-emerald-300 border border-emerald-800/40"
                title={
                  p.first_seen && p.last_seen
                    ? `${p.first_seen} → ${p.last_seen}, ${p.sightings} sightings`
                    : `${p.sightings} sightings`
                }
              >
                {p.name}
              </span>
            ))}
            {platesSeen?.slice(0, 3).map((plate) => (
              <span
                key={plate}
                className="px-1.5 py-0.5 text-[10px] rounded bg-accent/20 text-accent border border-accent/40 font-mono"
              >
                {plate}
              </span>
            ))}
            {topObjects.map(([label, count]) => (
              <span
                key={label}
                className="px-1.5 py-0.5 text-[10px] rounded bg-blue-900/30 text-blue-300 border border-blue-800/40"
              >
                {label} ×{count}
              </span>
            ))}
            {providerName && (
              <span className="ml-auto text-[10px] text-muted-foreground/70">
                {providerName}
                {triggerReason && triggerReason !== "timer" && triggerReason !== "event_close"
                  ? ` · ${triggerReason}`
                  : ""}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
