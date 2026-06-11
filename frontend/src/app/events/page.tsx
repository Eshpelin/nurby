"use client";

/**
 * Alerts review center. Every fired event across the deployment in one
 * place: filter by camera, rule, reviewed state, and time range; expand
 * for payload and notes; acknowledge or mute inline (parity with the
 * Telegram buttons); export the current view as CSV for audit.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@/lib/auth";
import { timeAgo, formatDateTime } from "@/lib/time";
import { EventNotesPanel } from "@/components/rules/EventNotesPanel";
import { EventEvidence } from "@/components/EventEvidence";
import type { Camera, EventEntry, Rule } from "@/components/rules/types";

const PAGE_SIZE = 50;

const RANGES = [
  { value: "24h", label: "Last 24h", hours: 24 },
  { value: "7d", label: "Last 7 days", hours: 24 * 7 },
  { value: "30d", label: "Last 30 days", hours: 24 * 30 },
  { value: "all", label: "All time", hours: 0 },
] as const;

type RangeValue = (typeof RANGES)[number]["value"];

export default function EventsPage() {
  const { authFetch } = useAuth();
  const [events, setEvents] = useState<EventEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const [cameras, setCameras] = useState<Camera[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);

  const [cameraFilter, setCameraFilter] = useState("");
  const [ruleFilter, setRuleFilter] = useState("");
  const [ackedFilter, setAckedFilter] = useState<"" | "false" | "true">("");
  const [severityFilter, setSeverityFilter] = useState<"" | "alert" | "detection">("alert");
  const [range, setRange] = useState<RangeValue>("7d");

  const ruleNames = useMemo(() => {
    const m = new Map<string, string>();
    for (const r of rules) m.set(r.id, r.name);
    return m;
  }, [rules]);

  const cameraNames = useMemo(() => {
    const m = new Map<string, string>();
    for (const c of cameras) m.set(c.id, c.name);
    return m;
  }, [cameras]);

  const buildQuery = useCallback(
    (offset: number) => {
      const params = new URLSearchParams();
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(offset));
      if (cameraFilter) params.set("camera_id", cameraFilter);
      if (ruleFilter) params.set("rule_id", ruleFilter);
      if (ackedFilter) params.set("acked", ackedFilter);
      if (severityFilter) params.set("severity", severityFilter);
      const hours = RANGES.find((r) => r.value === range)?.hours ?? 0;
      if (hours > 0) {
        params.set("from", new Date(Date.now() - hours * 3600_000).toISOString());
      }
      return params;
    },
    [cameraFilter, ruleFilter, ackedFilter, severityFilter, range]
  );

  const fetchEvents = useCallback(
    async (offset = 0) => {
      if (offset === 0) setLoading(true);
      else setLoadingMore(true);
      setError(null);
      try {
        const res = await authFetch(`/api/events/history?${buildQuery(offset)}`);
        if (!res.ok) throw new Error(`Failed to load alerts (${res.status})`);
        const list: EventEntry[] = await res.json();
        setEvents((prev) => (offset === 0 ? list : [...prev, ...list]));
        setHasMore(list.length === PAGE_SIZE);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load alerts");
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [authFetch, buildQuery]
  );

  useEffect(() => {
    fetchEvents(0);
  }, [fetchEvents]);

  useEffect(() => {
    (async () => {
      try {
        const [cr, rr] = await Promise.all([
          authFetch("/api/cameras"),
          authFetch("/api/rules"),
        ]);
        if (cr.ok) setCameras(await cr.json());
        if (rr.ok) setRules(await rr.json());
      } catch {
        /* filters degrade to raw ids */
      }
    })();
  }, [authFetch]);

  const patchEvent = useCallback((updated: EventEntry) => {
    setEvents((prev) => prev.map((e) => (e.id === updated.id ? { ...e, ...updated } : e)));
  }, []);

  const ack = useCallback(
    async (id: string) => {
      try {
        const res = await authFetch(`/api/events/${id}/ack`, { method: "POST" });
        if (res.ok) patchEvent(await res.json());
      } catch {
        /* leave row as-is */
      }
    },
    [authFetch, patchEvent]
  );

  const mute = useCallback(
    async (id: string) => {
      try {
        const res = await authFetch(`/api/events/${id}/mute?duration_seconds=600`, {
          method: "POST",
        });
        if (res.ok) patchEvent(await res.json());
      } catch {
        /* leave row as-is */
      }
    },
    [authFetch, patchEvent]
  );

  const downloadCsv = useCallback(async () => {
    try {
      const params = buildQuery(0);
      params.delete("limit");
      params.delete("offset");
      const res = await authFetch(`/api/events/export.csv?${params}`);
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "events.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    }
  }, [authFetch, buildQuery]);

  const cameraOf = (ev: EventEntry): string => {
    const payload = (ev.payload || {}) as Record<string, unknown>;
    const cid = payload.camera_id as string | undefined;
    const pname = payload.camera_name as string | undefined;
    if (cid && cameraNames.get(cid)) return cameraNames.get(cid)!;
    if (pname) return pname;
    return cid ? cid.slice(0, 8) : "";
  };

  const descriptionOf = (ev: EventEntry): string => {
    const payload = (ev.payload || {}) as Record<string, unknown>;
    return (
      (payload.vlm_description as string) ||
      (payload.status_reason as string) ||
      ""
    );
  };

  const selectClass =
    "px-2.5 py-1.5 text-sm rounded-md border border-border bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-accent";

  return (
    <div className="max-w-5xl mx-auto p-6">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Alerts</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Every rule that fired, across all cameras. Review, acknowledge, export.
          </p>
        </div>
        <button
          type="button"
          onClick={downloadCsv}
          className="px-3 py-1.5 text-sm rounded-md border border-border hover:border-muted-foreground/40 text-muted-foreground hover:text-foreground transition-colors"
          title="Download the current view (all matching rows, not just the page) as CSV"
        >
          Export CSV
        </button>
      </div>

      <div className="flex items-center gap-1 mb-3">
        {([
          { v: "alert", l: "Alerts" },
          { v: "detection", l: "Detections" },
          { v: "", l: "Everything" },
        ] as const).map((t) => (
          <button
            key={t.v}
            type="button"
            onClick={() => setSeverityFilter(t.v)}
            className={`px-3 py-1.5 text-sm rounded-md border transition-colors ${
              severityFilter === t.v
                ? "border-foreground/40 bg-muted text-foreground font-medium"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.l}
          </button>
        ))}
        <span className="ml-2 text-[11px] text-muted-foreground">
          Alerts are the push-worthy tier; detections are kept for review.
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <select value={range} onChange={(e) => setRange(e.target.value as RangeValue)} className={selectClass} aria-label="Time range">
          {RANGES.map((r) => (
            <option key={r.value} value={r.value}>{r.label}</option>
          ))}
        </select>
        <select value={cameraFilter} onChange={(e) => setCameraFilter(e.target.value)} className={selectClass} aria-label="Camera filter">
          <option value="">All cameras</option>
          {cameras.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <select value={ruleFilter} onChange={(e) => setRuleFilter(e.target.value)} className={selectClass} aria-label="Rule filter">
          <option value="">All rules</option>
          {rules.map((r) => (
            <option key={r.id} value={r.id}>{r.name}</option>
          ))}
        </select>
        <select value={ackedFilter} onChange={(e) => setAckedFilter(e.target.value as "" | "false" | "true")} className={selectClass} aria-label="Review state filter">
          <option value="">Reviewed + unreviewed</option>
          <option value="false">Unreviewed only</option>
          <option value="true">Reviewed only</option>
        </select>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-muted-foreground py-12 text-center">Loading alerts.</p>
      ) : events.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border py-12 text-center">
          <p className="text-sm text-muted-foreground">
            No alerts match these filters. When a rule fires, it lands here.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {events.map((ev) => {
            const acked = !!(ev.acked_at || ev.acknowledged_at);
            const muted = !!ev.muted_until && new Date(ev.muted_until) > new Date();
            const expanded = expandedId === ev.id;
            const desc = descriptionOf(ev);
            return (
              <div
                key={ev.id}
                onClick={() => setExpandedId(expanded ? null : ev.id)}
                className="rounded-md border border-border bg-card p-3 cursor-pointer hover:border-muted-foreground/30 transition-colors"
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className={`w-2 h-2 rounded-full flex-shrink-0 ${
                      ev.action_status === "success"
                        ? "bg-green-500"
                        : ev.action_status === "failed"
                        ? "bg-red-500"
                        : "bg-yellow-500"
                    }`}
                  />
                  <span className="text-sm font-medium">
                    {ev.rule_id ? ruleNames.get(ev.rule_id) || "Deleted rule" : "Rule"}
                  </span>
                  {cameraOf(ev) && (
                    <span className="px-1.5 py-0.5 text-[10px] rounded bg-muted text-muted-foreground">
                      {cameraOf(ev)}
                    </span>
                  )}
                  {acked && (
                    <span className="px-1.5 py-0.5 text-[10px] rounded bg-green-500/15 text-green-400 border border-green-500/30">
                      ✓ Reviewed{ev.acked_via ? ` (${ev.acked_via})` : ""}
                    </span>
                  )}
                  {muted && (
                    <span className="px-1.5 py-0.5 text-[10px] rounded bg-muted text-muted-foreground">
                      🔕 Muted
                    </span>
                  )}
                  <span
                    className="ml-auto text-[11px] text-muted-foreground"
                    title={formatDateTime(ev.fired_at)}
                  >
                    {timeAgo(ev.fired_at)}
                  </span>
                </div>
                {desc && (
                  <div className="mt-1 text-xs text-muted-foreground line-clamp-2">{desc}</div>
                )}
                {expanded && (
                  <div className="mt-3 pt-3 border-t border-border" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center gap-2 mb-3">
                      {!acked && (
                        <button
                          type="button"
                          onClick={() => ack(ev.id)}
                          className="px-2 py-1 text-[11px] rounded-md bg-green-500/10 border border-green-500/30 text-green-400 hover:bg-green-500/20 transition-colors"
                        >
                          ✓ Acknowledge
                        </button>
                      )}
                      {!muted && (
                        <button
                          type="button"
                          onClick={() => mute(ev.id)}
                          className="px-2 py-1 text-[11px] rounded-md border border-border text-muted-foreground hover:text-foreground hover:border-muted-foreground/40 transition-colors"
                          title="Silence re-sends of this alert for 10 minutes"
                        >
                          🔕 Mute 10m
                        </button>
                      )}
                      {ev.action_status === "failed" && ev.action_error && (
                        <span className="text-[11px] text-red-400 truncate">{ev.action_error}</span>
                      )}
                    </div>
                    {ev.payload ? (
                      <EventEvidence payload={ev.payload} />
                    ) : (
                      <p className="text-[11px] text-muted-foreground">No payload recorded.</p>
                    )}
                    <EventNotesPanel eventId={ev.id} />
                  </div>
                )}
              </div>
            );
          })}
          {hasMore && (
            <button
              type="button"
              onClick={() => fetchEvents(events.length)}
              disabled={loadingMore}
              className="w-full px-3 py-2 text-sm rounded-md border border-border text-muted-foreground hover:text-foreground hover:border-muted-foreground/40 transition-colors disabled:opacity-50"
            >
              {loadingMore ? "Loading." : "Load more"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
