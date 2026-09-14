"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/time";
import { ActivityFilterBar, activeKind } from "@/components/activity/ActivityFilterBar";
import TimelinePage from "@/app/timeline/page";

/**
 * Activity: what happened (docs/ia-rollout.md).
 *
 * "All" and "Sightings" are the timeline. Incidents, Journeys,
 * Conversations and Camera recaps are the four kinds web never had a
 * page for: they were reachable only through the dashboard and the
 * follow feed. Each is a plain list here; the detail views they link to
 * already exist.
 */
export default function ActivityPage() {
  return (
    <Suspense fallback={null}>
      <ActivityInner />
    </Suspense>
  );
}

function ActivityInner() {
  const params = useSearchParams();
  const kind = activeKind("/activity", params.get("kind"));

  if (kind === "all" || kind === "sightings") {
    // The timeline page already carries the filter bar.
    return <TimelinePage />;
  }

  return (
    <div className="px-6 py-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Activity</h1>
        <div className="mt-4">
          <ActivityFilterBar />
        </div>
      </div>
      {kind === "incidents" && <KindList path="/api/incidents" render={IncidentRow} empty="No incidents yet. Nurby groups repeat sightings of the same subject into one incident." />}
      {kind === "journeys" && <KindList path="/api/journeys" render={JourneyRow} empty="No journeys yet. A journey is one subject followed across several cameras." />}
      {kind === "conversations" && <KindList path="/api/conversations" render={ConversationRow} empty="No conversations yet. Speech near a camera is grouped into a conversation." />}
      {kind === "recaps" && <KindList path="/api/digests" render={RecapRow} empty="No camera recaps yet. The first appears after a full period has passed." />}
    </div>
  );
}

type Row = Record<string, unknown>;

function KindList({ path, render, empty }: { path: string; render: (r: Row) => React.ReactNode; empty: string }) {
  const { authFetch } = useAuth();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await authFetch(`${path}?limit=50`);
        if (!res.ok) throw new Error(`${res.status}`);
        const body = await res.json();
        if (!cancelled) setRows(Array.isArray(body) ? body : body.items ?? []);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "failed");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [authFetch, path]);

  if (error) return <p className="text-sm text-muted-foreground">Could not load: {error}</p>;
  if (rows === null) return <p className="text-sm text-muted-foreground">Loading</p>;
  if (rows.length === 0) return <p className="text-sm text-muted-foreground max-w-prose">{empty}</p>;
  return <ul className="space-y-2">{rows.map((r, i) => <li key={String(r.id ?? i)}>{render(r)}</li>)}</ul>;
}

function Card({ children }: { children: React.ReactNode }) {
  return <div className="rounded-lg border border-border bg-card px-4 py-3">{children}</div>;
}

/** Subject text for incidents and journeys. Never a raw cluster id. */
function subjectLabel(kind: unknown, key: unknown): string {
  const k = String(key ?? "");
  switch (kind) {
    case "person":
      return k.split(",").join(", ");
    case "cluster":
      return `Recurring stranger ${k.split(",")[0].slice(0, 8)}`;
    case "body":
      return "Unrecognized person (matched by appearance)";
    case "unknown":
      return "Unknown person";
    case "object":
      return k ? k.charAt(0).toUpperCase() + k.slice(1) : "Object";
    default:
      return "Motion";
  }
}

function IncidentRow(r: Row) {
  return (
    <Card>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-medium">{subjectLabel(r.signature_kind, r.signature_key)}</span>
        <span className="text-xs text-muted-foreground">{formatDateTime(String(r.started_at))}</span>
      </div>
      {typeof r.summary_text === "string" && r.summary_text && (
        <p className="text-sm text-muted-foreground mt-1">{r.summary_text}</p>
      )}
    </Card>
  );
}

function JourneyRow(r: Row) {
  const segs = Array.isArray(r.segments) ? (r.segments as Row[]) : [];
  const path: string[] = [];
  for (const s of segs) {
    const n = String(s.camera_name ?? "");
    if (n && path[path.length - 1] !== n) path.push(n);
  }
  return (
    <Card>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-medium">{subjectLabel(r.subject_kind, r.subject_key)}</span>
        <span className="text-xs text-muted-foreground">{formatDateTime(String(r.started_at))}</span>
      </div>
      {path.length > 0 && <p className="text-sm text-muted-foreground mt-1">{path.join(" → ")}</p>}
    </Card>
  );
}

function ConversationRow(r: Row) {
  return (
    <Card>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-medium">Conversation · {String(r.transcript_count ?? 0)} lines</span>
        <span className="text-xs text-muted-foreground">{formatDateTime(String(r.started_at))}</span>
      </div>
      {typeof r.summary_text === "string" && r.summary_text && (
        <p className="text-sm text-muted-foreground mt-1">{r.summary_text}</p>
      )}
    </Card>
  );
}

function RecapRow(r: Row) {
  return (
    <Card>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-medium">{r.camera_id ? "Camera recap" : "All cameras"} · {String(r.period ?? "")}</span>
        <span className="text-xs text-muted-foreground">{formatDateTime(String(r.generated_at))}</span>
      </div>
      <p className="text-sm mt-1">{String(r.summary ?? "")}</p>
    </Card>
  );
}
