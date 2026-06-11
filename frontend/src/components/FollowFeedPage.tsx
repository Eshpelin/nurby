"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/time";

interface SubjectPerson {
  kind: "person";
  id: string;
  display_name: string;
  relationship: string | null;
  photo_path: string | null;
}

interface SubjectCluster {
  kind: "cluster";
  id: string;
  auto_label: string | null;
  auto_label_number: number | null;
  appearance_description: string | null;
  sample_thumbnail_path: string | null;
}

type Subject = SubjectPerson | SubjectCluster;

interface CameraSeen {
  id: string;
  name: string;
  count: number;
  first_seen_at: string | null;
  last_seen_at: string | null;
}

interface Stats {
  total_sightings: number;
  first_seen_at: string | null;
  last_seen_at: string | null;
  cameras_seen: CameraSeen[];
  hour_buckets: Record<string, number>;
  incidents_count: number;
  conversations_count: number;
  recordings_count: number;
}

interface FeedItemBase {
  kind: string;
  id: string;
  camera_id: string;
  camera_name: string | null;
  ts: string;
}

interface FeedObservation extends FeedItemBase {
  kind: "observation";
  ended_at: string | null;
  vlm_description: string | null;
  thumbnail_path: string | null;
  incident_id: string | null;
  refined_by_provider_name: string | null;
}

interface FeedIncident extends FeedItemBase {
  kind: "incident";
  last_seen_at: string;
  ended_at: string | null;
  finalized: boolean;
  occurrence_count: number;
  summary_text: string | null;
  signature_kind: string;
  signature_key: string;
  thumbnails: { obs_id: string; path: string | null; ts: string }[] | null;
}

interface FeedConversation extends FeedItemBase {
  kind: "conversation";
  ended_at: string;
  transcript_count: number;
  finalized: boolean;
  summary_text: string | null;
  cleaned_text: string | null;
  has_clip: boolean;
}

interface FeedTranscript extends FeedItemBase {
  kind: "transcript";
  ended_at: string;
  text: string;
  audio_capture_id: string | null;
  conversation_id: string | null;
}

interface FeedRecording extends FeedItemBase {
  kind: "recording";
  ended_at: string | null;
  duration_seconds: number | null;
  file_path: string;
  thumbnail_path: string | null;
}

type FeedItem =
  | FeedObservation
  | FeedIncident
  | FeedConversation
  | FeedTranscript
  | FeedRecording;

interface Bundle {
  subject: Subject;
  stats: Stats;
  feed: FeedItem[];
}

interface Props {
  // Either ``person`` or ``cluster``. Drives the API path + page heading.
  kind: "person" | "cluster";
  id: string;
}

const RANGES = [
  { v: 86400, l: "24 hours" },
  { v: 604800, l: "7 days" },
  { v: 2592000, l: "30 days" },
  { v: 0, l: "All time" },
] as const;

/**
 * Investigative timeline for one subject. Renders a header with
 * stats, a 24h activity heatmap, a camera filter strip, and a
 * unified feed of every observation, incident, conversation,
 * transcript, and recording the subject appeared in.
 */
export function FollowFeedPage({ kind, id }: Props) {
  const { authFetch, token } = useAuth();
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rangeS, setRangeS] = useState<number>(604800); // 7 days
  const [cameraFilter, setCameraFilter] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ limit: "200" });
      if (rangeS > 0) {
        const fromIso = new Date(Date.now() - rangeS * 1000).toISOString();
        params.set("from", fromIso);
      }
      if (cameraFilter) params.set("camera_id", cameraFilter);
      const url =
        kind === "person"
          ? `/api/persons/${id}/follow?${params}`
          : `/api/persons/clusters/${id}/follow?${params}`;
      const res = await authFetch(url);
      if (!res.ok) throw new Error(`status ${res.status}`);
      const data: Bundle = await res.json();
      setBundle(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [authFetch, kind, id, rangeS, cameraFilter]);

  useEffect(() => {
    refresh();
    const i = setInterval(refresh, 30000);
    return () => clearInterval(i);
  }, [refresh]);

  const subjectName = useMemo(() => {
    if (!bundle) return "";
    if (bundle.subject.kind === "person") return bundle.subject.display_name;
    const c = bundle.subject;
    return c.auto_label || `Stranger ${String(c.id).slice(0, 8)}`;
  }, [bundle]);

  const heatPeak = useMemo(() => {
    if (!bundle) return 1;
    const max = Math.max(0, ...Object.values(bundle.stats.hour_buckets));
    return max || 1;
  }, [bundle]);

  return (
    <div className="px-6 py-6 max-w-5xl mx-auto">
      <div className="flex items-center gap-3 mb-5">
        <Link href="/people" className="text-muted-foreground hover:text-foreground text-sm">
          ← People
        </Link>
        <span className="text-muted-foreground">/</span>
        <h1 className="text-lg font-semibold flex items-center gap-2">
          <FollowIcon className="w-5 h-5 text-accent" />
          Following {subjectName}
        </h1>
      </div>

      {bundle && (
        <FollowHeader
          subject={bundle.subject}
          stats={bundle.stats}
          token={token}
          rangeS={rangeS}
          setRangeS={setRangeS}
          heatPeak={heatPeak}
        />
      )}

      {bundle && bundle.stats.cameras_seen.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap mb-4">
          <span className="text-[10px] uppercase tracking-wider text-muted-foreground mr-1">
            Cameras
          </span>
          <button
            type="button"
            onClick={() => setCameraFilter(null)}
            className={`px-2 py-1 text-xs rounded-md border transition-colors ${
              cameraFilter === null
                ? "border-accent bg-accent/10 text-accent-foreground"
                : "border-border text-muted-foreground hover:text-foreground"
            }`}
          >
            All
          </button>
          {bundle.stats.cameras_seen.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() =>
                setCameraFilter((prev) => (prev === c.id ? null : c.id))
              }
              className={`px-2 py-1 text-xs rounded-md border transition-colors ${
                cameraFilter === c.id
                  ? "border-accent bg-accent/10 text-accent-foreground"
                  : "border-border text-muted-foreground hover:text-foreground"
              }`}
            >
              {c.name}
              <span className="ml-1 text-[10px] text-muted-foreground/80">
                ×{c.count}
              </span>
            </button>
          ))}
        </div>
      )}

      {loading && !bundle ? (
        <div className="text-sm text-muted-foreground">Building timeline.</div>
      ) : error ? (
        <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 text-xs text-danger">
          {error}
        </div>
      ) : bundle && bundle.feed.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-card/30 p-8 text-center">
          <h3 className="text-sm font-medium mb-1">Nothing to show</h3>
          <p className="text-xs text-muted-foreground max-w-md mx-auto">
            No sightings in this window. Try widening the time range or
            removing the camera filter.
          </p>
        </div>
      ) : bundle ? (
        <div className="space-y-2">
          {bundle.feed.map((item) => (
            <FeedRow key={`${item.kind}-${item.id}`} item={item} token={token} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function FollowHeader({
  subject,
  stats,
  token,
  rangeS,
  setRangeS,
  heatPeak,
}: {
  subject: Subject;
  stats: Stats;
  token: string | null;
  rangeS: number;
  setRangeS: (v: number) => void;
  heatPeak: number;
}) {
  const photoUrl =
    subject.kind === "person" && subject.photo_path && token
      ? `/api/persons/${subject.id}/photo?token=${encodeURIComponent(token)}`
      : null;
  const headlineSub =
    subject.kind === "person"
      ? subject.relationship || "Person"
      : subject.appearance_description || "Recurring stranger";

  const formatTs = (iso: string | null) =>
    iso ? formatDateTime(iso) : "—";
  return (
    <div className="rounded-xl border border-border bg-card/40 p-4 mb-5">
      <div className="flex items-center gap-4 mb-4">
        {photoUrl ? (
          <img
            src={photoUrl}
            alt={subject.kind === "person" ? subject.display_name : ""}
            className="w-16 h-16 rounded-full object-cover border border-border"
          />
        ) : (
          <div className="w-16 h-16 rounded-full bg-muted border border-border flex items-center justify-center text-2xl text-muted-foreground">
            ?
          </div>
        )}
        <div className="flex-1 min-w-0">
          <h2 className="text-xl font-semibold truncate">
            {subject.kind === "person"
              ? subject.display_name
              : subject.auto_label || "Stranger"}
          </h2>
          <p className="text-xs text-muted-foreground">{headlineSub}</p>
        </div>
        <div className="flex items-center gap-1">
          {RANGES.map((r) => (
            <button
              key={r.v}
              type="button"
              onClick={() => setRangeS(r.v)}
              className={`px-2.5 py-1 text-xs rounded-md border transition-colors ${
                rangeS === r.v
                  ? "border-accent bg-accent/10 text-accent-foreground"
                  : "border-border text-muted-foreground hover:text-foreground"
              }`}
            >
              {r.l}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs mb-4">
        <Stat label="Sightings" value={String(stats.total_sightings)} />
        <Stat
          label="Cameras"
          value={String(stats.cameras_seen.length)}
        />
        <Stat label="First seen" value={formatTs(stats.first_seen_at)} />
        <Stat label="Last seen" value={formatTs(stats.last_seen_at)} />
        <Stat label="Incidents" value={String(stats.incidents_count)} />
        <Stat label="Conversations" value={String(stats.conversations_count)} />
        <Stat
          label="Recordings"
          value={String(stats.recordings_count)}
          hint="overlapping presence"
        />
        <Stat
          label="Peak hour"
          value={peakHour(stats.hour_buckets) ?? "—"}
        />
      </div>

      <div>
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">
          Activity by hour
        </div>
        <div className="flex items-end gap-1 h-12">
          {Array.from({ length: 24 }).map((_, h) => {
            const key = String(h).padStart(2, "0");
            const v = stats.hour_buckets[key] || 0;
            const pct = (v / heatPeak) * 100;
            return (
              <div
                key={key}
                className="flex-1 bg-violet-500/20 border-t border-violet-400/50 rounded-sm relative"
                style={{ height: `${Math.max(2, pct)}%` }}
                title={`${key}:00 — ${v} sightings`}
              />
            );
          })}
        </div>
        <div className="flex justify-between text-[9px] text-muted-foreground/70 font-mono mt-1">
          <span>00</span>
          <span>06</span>
          <span>12</span>
          <span>18</span>
          <span>23</span>
        </div>
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-md border border-border/60 bg-background/40 px-3 py-2">
      <div className="text-[9px] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="font-medium truncate" title={hint}>{value}</div>
      {hint && <div className="text-[9px] text-muted-foreground/70">{hint}</div>}
    </div>
  );
}

function peakHour(buckets: Record<string, number>): string | null {
  let best: string | null = null;
  let n = 0;
  for (const [h, v] of Object.entries(buckets)) {
    if (v > n) {
      best = h;
      n = v;
    }
  }
  return best == null ? null : `${best}:00 (${n})`;
}

function FeedRow({ item, token }: { item: FeedItem; token: string | null }) {
  const time = formatDateTime(item.ts);
  if (item.kind === "observation") {
    return (
      <div className="rounded-lg border border-border bg-card/40 p-3">
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground mb-1.5">
          <span className="font-mono">{time}</span>
          <span>·</span>
          <span>{item.camera_name || "Camera"}</span>
          {item.refined_by_provider_name && (
            <span className="ml-auto text-sky-300">
              ✨ refined
            </span>
          )}
        </div>
        <div className="flex gap-3">
          {item.thumbnail_path && (
            <div className="w-24 h-16 flex-shrink-0 bg-black/50 rounded overflow-hidden">
              <img
                src={`/api/observations/${item.id}/thumbnail${
                  token ? `?token=${token}` : ""
                }`}
                alt=""
                className="w-full h-full object-cover"
              />
            </div>
          )}
          <p className="text-sm leading-relaxed flex-1">
            {item.vlm_description || "Motion detected"}
          </p>
        </div>
      </div>
    );
  }
  if (item.kind === "incident") {
    return (
      <div
        className={`rounded-lg border p-3 ${
          item.finalized
            ? "border-emerald-700/40 bg-emerald-950/15"
            : "border-violet-700/40 bg-violet-950/15"
        }`}
      >
        <div className="flex items-center gap-2 text-[11px] mb-1.5">
          <span
            className={`font-medium uppercase tracking-wider ${
              item.finalized ? "text-emerald-300" : "text-violet-300"
            }`}
          >
            {item.finalized ? "Incident closed" : "Incident · live"}
          </span>
          <span className="text-muted-foreground">·</span>
          <span className="text-muted-foreground">{item.camera_name || "Camera"}</span>
          <span className="text-muted-foreground">·</span>
          <span className="text-muted-foreground font-mono">
            {item.occurrence_count}× · {time}
          </span>
        </div>
        {item.summary_text ? (
          <p className="text-sm leading-relaxed">{item.summary_text}</p>
        ) : (
          <p className="text-xs text-muted-foreground italic">
            Live incident, no summary yet.
          </p>
        )}
      </div>
    );
  }
  if (item.kind === "conversation") {
    return (
      <div className="rounded-lg border border-emerald-700/40 bg-emerald-950/15 p-3">
        <div className="flex items-center gap-2 text-[11px] mb-1.5">
          <span className="font-medium uppercase tracking-wider text-emerald-300">
            Conversation
          </span>
          <span className="text-muted-foreground">·</span>
          <span className="text-muted-foreground">{item.camera_name || "Camera"}</span>
          <span className="text-muted-foreground">·</span>
          <span className="text-muted-foreground font-mono">
            {item.transcript_count} msg · {time}
          </span>
        </div>
        {item.summary_text ? (
          <p className="text-sm leading-relaxed">{item.summary_text}</p>
        ) : (
          <p className="text-xs text-muted-foreground italic">
            Conversation in progress.
          </p>
        )}
        {item.has_clip && token && (
          <video
            controls
            preload="metadata"
            className="w-full mt-2 rounded border border-border bg-black"
            src={`/api/conversations/${item.id}/clip?token=${encodeURIComponent(token)}`}
          />
        )}
      </div>
    );
  }
  if (item.kind === "transcript") {
    return (
      <div className="rounded-lg border border-emerald-700/30 bg-emerald-950/10 p-3">
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground mb-1">
          <span className="text-emerald-300 uppercase tracking-wider">
            Transcript
          </span>
          <span>·</span>
          <span>{item.camera_name || "Camera"}</span>
          <span>·</span>
          <span className="font-mono">{time}</span>
        </div>
        <p className="text-sm italic">{item.text}</p>
      </div>
    );
  }
  // recording
  return (
    <div className="rounded-lg border border-blue-700/40 bg-blue-950/15 p-3">
      <div className="flex items-center gap-2 text-[11px] mb-1.5">
        <span className="font-medium uppercase tracking-wider text-blue-300">
          Recording
        </span>
        <span className="text-muted-foreground">·</span>
        <span className="text-muted-foreground">{item.camera_name || "Camera"}</span>
        <span className="text-muted-foreground">·</span>
        <span className="text-muted-foreground font-mono">
          {item.duration_seconds != null
            ? `${Math.round(item.duration_seconds)}s · `
            : ""}
          {time}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">
        Recording overlaps the subject's presence on this camera. Open the
        Recordings page for inline playback.
      </p>
    </div>
  );
}

export function FollowIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="10" />
      <circle cx="12" cy="12" r="3" />
      <line x1="12" y1="2" x2="12" y2="5" />
      <line x1="12" y1="19" x2="12" y2="22" />
      <line x1="2" y1="12" x2="5" y2="12" />
      <line x1="19" y1="12" x2="22" y2="12" />
    </svg>
  );
}
