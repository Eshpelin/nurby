"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";
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
  const { user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
  const kind = activeKind("/activity", params.get("kind"));

  if (kind === "all" || kind === "sightings") {
    // The timeline page already carries the filter bar.
    return <TimelinePage />;
  }

  return (
    <div className="px-6 py-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">{t("activity.title")}</h1>
        <div className="mt-4">
          <ActivityFilterBar />
        </div>
      </div>
      {kind === "incidents" && <KindList path="/api/incidents" render={IncidentRow} empty={t("activity.empty_incidents")} />}
      {kind === "journeys" && <KindList path="/api/journeys" render={JourneyRow} empty={t("activity.empty_journeys")} />}
      {kind === "conversations" && <KindList path="/api/conversations" render={ConversationRow} empty={t("activity.empty_conversations")} />}
      {kind === "recaps" && <KindList path="/api/digests" render={RecapRow} empty={t("activity.empty_recaps")} />}
    </div>
  );
}

type Row = Record<string, unknown>;

function KindList({ path, render: Render, empty }: { path: string; render: React.ComponentType<{ row: Row }>; empty: string }) {
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

  const { user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
  if (error) return <p className="text-sm text-muted-foreground">{t("activity.load_error", { error })}</p>;
  if (rows === null) return <p className="text-sm text-muted-foreground">{t("activity.loading")}</p>;
  if (rows.length === 0) return <p className="text-sm text-muted-foreground max-w-prose">{empty}</p>;
  return <ul className="space-y-2">{rows.map((r, i) => <li key={String(r.id ?? i)}><Render row={r} /></li>)}</ul>;
}

function Card({ children }: { children: React.ReactNode }) {
  return <div className="rounded-lg border border-border bg-card px-4 py-3">{children}</div>;
}

/** Subject text for incidents and journeys. Never a raw cluster id. */
function subjectLabel(kind: unknown, key: unknown, t: (key: string) => string): string {
  const k = String(key ?? "");
  switch (kind) {
    case "person":
      return k.split(",").join(", ");
    case "cluster":
      return `${t("activity.recurring_stranger")} ${k.split(",")[0].slice(0, 8)}`;
    case "body":
      return t("activity.unrecognized_person");
    case "unknown":
      return t("activity.unknown_person");
    case "object":
      return k ? k.charAt(0).toUpperCase() + k.slice(1) : t("activity.object");
    default:
      return t("activity.motion");
  }
}

function IncidentRow({ row: r }: { row: Row }) {
  const { user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
  return (
    <Card>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-medium">{subjectLabel(r.signature_kind, r.signature_key, t)}</span>
        <span className="text-xs text-muted-foreground">{formatDateTime(String(r.started_at))}</span>
      </div>
      {typeof r.summary_text === "string" && r.summary_text && (
        <p className="text-sm text-muted-foreground mt-1">{r.summary_text}</p>
      )}
    </Card>
  );
}

function JourneyRow({ row: r }: { row: Row }) {
  const { user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
  const segs = Array.isArray(r.segments) ? (r.segments as Row[]) : [];
  const path: string[] = [];
  for (const s of segs) {
    const n = String(s.camera_name ?? "");
    if (n && path[path.length - 1] !== n) path.push(n);
  }
  return (
    <Card>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-medium">{subjectLabel(r.subject_kind, r.subject_key, t)}</span>
        <span className="text-xs text-muted-foreground">{formatDateTime(String(r.started_at))}</span>
      </div>
      {path.length > 0 && <p className="text-sm text-muted-foreground mt-1">{path.join(" → ")}</p>}
    </Card>
  );
}

function ConversationRow({ row: r }: { row: Row }) {
  const { user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
  return (
    <Card>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-medium">{t("activity.conversation_count", { count: String(r.transcript_count ?? 0) })}</span>
        <span className="text-xs text-muted-foreground">{formatDateTime(String(r.started_at))}</span>
      </div>
      {typeof r.summary_text === "string" && r.summary_text && (
        <p className="text-sm text-muted-foreground mt-1">{r.summary_text}</p>
      )}
    </Card>
  );
}

function RecapRow({ row: r }: { row: Row }) {
  const { user } = useAuth();
  const t = (key: string) => translate(user?.locale, key);
  return (
    <Card>
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-medium">{r.camera_id ? t("activity.camera_recap") : t("activity.all_cameras")} · {String(r.period ?? "")}</span>
        <span className="text-xs text-muted-foreground">{formatDateTime(String(r.generated_at))}</span>
      </div>
      <p className="text-sm mt-1">{String(r.summary ?? "")}</p>
    </Card>
  );
}
