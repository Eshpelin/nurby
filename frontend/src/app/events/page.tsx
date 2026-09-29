"use client";

import { ActivityFilterBar } from "@/components/activity/ActivityFilterBar";

/**
 * Alerts review center. Every fired event across the deployment in one
 * place: filter by camera, rule, reviewed state, and time range; expand
 * for payload and notes; acknowledge or mute inline (parity with the
 * Telegram buttons); export the current view as CSV for audit.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { timeAgo, formatDateTime } from "@/lib/time";
import { EventNotesPanel } from "@/components/rules/EventNotesPanel";
import { EventFeedbackPanel } from "@/components/events/EventFeedback";
import { EventEvidence } from "@/components/EventEvidence";
import { ShareDialog } from "@/components/ShareDialog";
import { ReviewQueue } from "@/components/review/ReviewQueue";
import { translate } from "@/lib/i18n";
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
  const { authFetch, user } = useAuth();
  const locale = user?.locale;
  const t = useCallback((key: string, values?: Record<string, string | number>) => translate(locale, key, values), [locale]);
  const searchParams = useSearchParams();
  const [events, setEvents] = useState<EventEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  // Event being shared via an anonymous link (opens ShareDialog).
  const [shareEvent, setShareEvent] = useState<EventEntry | null>(null);

  const [cameras, setCameras] = useState<Camera[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);

  const [cameraFilter, setCameraFilter] = useState(() => searchParams.get("camera_id") ?? "");
  const [ruleFilter, setRuleFilter] = useState("");
  const [ackedFilter, setAckedFilter] = useState<"" | "false" | "true">("");
  const [severityFilter, setSeverityFilter] = useState<"" | "alert" | "detection">("alert");
  const [range, setRange] = useState<RangeValue>("7d");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [selectAllMatching, setSelectAllMatching] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkMessage, setBulkMessage] = useState<string | null>(null);

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
        if (!res.ok) throw new Error(`${t("events.load_failed")} (${res.status})`);
        const list: EventEntry[] = await res.json();
        setEvents((prev) => (offset === 0 ? list : [...prev, ...list]));
        setHasMore(list.length === PAGE_SIZE);
      } catch (e) {
        setError(e instanceof Error ? e.message : t("events.load_failed"));
      } finally {
        setLoading(false);
        setLoadingMore(false);
      }
    },
    [authFetch, buildQuery, t]
  );

  useEffect(() => {
    fetchEvents(0);
  }, [fetchEvents]);

  useEffect(() => {
    const alertId = searchParams.get("alert");
    if (!alertId || loading) return;
    if (events.some((event) => event.id === alertId)) {
      setExpandedId(alertId);
    }
  }, [events, loading, searchParams]);

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

  const openEvent = useCallback(async (id: string) => {
    setExpandedId((current) => (current === id ? null : id));
    try {
      const res = await authFetch(`/api/events/${id}/opened`, { method: "POST" });
      if (res.ok) patchEvent(await res.json());
    } catch {
      // Opening telemetry is best-effort and must not block alert review.
    }
  }, [authFetch, patchEvent]);

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
      if (!res.ok) throw new Error(`${t("events.export_failed")} (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "events.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("events.export_failed"));
    }
  }, [authFetch, buildQuery, t]);

  const selectionFilters = useCallback(() => {
    const hours = RANGES.find((r) => r.value === range)?.hours ?? 0;
    return {
      camera_id: cameraFilter || undefined,
      rule_id: ruleFilter || undefined,
      acked: ackedFilter === "" ? undefined : ackedFilter === "true",
      severity: severityFilter || undefined,
      from: hours > 0 ? new Date(Date.now() - hours * 3600_000).toISOString() : undefined,
    };
  }, [cameraFilter, ruleFilter, ackedFilter, severityFilter, range]);

  const downloadSelectedCsv = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (selectAllMatching) {
        const f = selectionFilters();
        if (f.camera_id) params.set("camera_id", f.camera_id);
        if (f.rule_id) params.set("rule_id", f.rule_id);
        if (f.acked !== undefined) params.set("acked", String(f.acked));
        if (f.severity) params.set("severity", f.severity);
        if (f.from) params.set("from", f.from);
      } else {
        for (const id of selectedIds) params.append("event_id", id);
      }
      const res = await authFetch(`/api/events/export.csv?${params}`);
      if (!res.ok) throw new Error(`${t("events.export_failed")} (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "events.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setBulkMessage(e instanceof Error ? e.message : t("events.export_failed"));
    }
  }, [authFetch, selectedIds, selectAllMatching, selectionFilters, t]);

  const bulkDelete = useCallback(async () => {
    if (!selectAllMatching && selectedIds.size === 0) return;
    setBulkBusy(true);
    setBulkMessage(null);
    try {
      const body = selectAllMatching
        ? { all_matching: true, filters: selectionFilters() }
        : { ids: [...selectedIds] };
      const previewRes = await authFetch("/api/events/bulk/preview", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const preview = await previewRes.json().catch(() => ({}));
      if (!previewRes.ok) throw new Error(preview.detail || `Preview failed (${previewRes.status})`);
      const camerasInScope = (preview.cameras || [])
        .map((id: string) => cameraNames.get(id) || t("events.unknown_camera"))
        .join(", ");
      const scope = selectAllMatching ? t("events.all_matching") : t("events.selected", { count: selectedIds.size });
      if (!window.confirm(
        t("events.delete_confirm", {
          count: preview.matching,
          plural: preview.matching === 1 ? "" : "s",
          scope,
          cameras: camerasInScope || t("incident.nobody"),
          linked: preview.linked_recordings || 0,
        })
      )) return;
      const res = await authFetch("/api/events/bulk/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const result = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(result.detail || `${t("events.bulk_delete_failed")} (${res.status})`);
      const removed = new Set(selectedIds);
      setEvents((prev) => prev.filter((e) => !removed.has(e.id)));
      setSelectedIds(new Set());
      setSelectAllMatching(false);
      if (selectAllMatching) await fetchEvents(0);
      setBulkMessage(t("events.deleted_result", {
        count: result.deleted,
        plural: result.deleted === 1 ? "" : "s",
      }));
    } catch (e) {
      setBulkMessage(e instanceof Error ? e.message : t("events.bulk_delete_failed"));
    } finally {
      setBulkBusy(false);
    }
  }, [authFetch, cameraNames, fetchEvents, selectedIds, selectAllMatching, selectionFilters, t]);

  useEffect(() => {
    setSelectedIds(new Set());
    setSelectAllMatching(false);
  }, [cameraFilter, ruleFilter, ackedFilter, severityFilter, range]);

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
          <h1 className="text-2xl font-semibold tracking-tight">{t("events.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {t("events.subtitle")}
          </p>
        </div>
        <button
          type="button"
          onClick={downloadCsv}
          className="px-3 py-1.5 text-sm rounded-md border border-border hover:border-muted-foreground/40 text-muted-foreground hover:text-foreground transition-colors"
          title={t("events.export_title")}
        >
          {t("events.export_csv")}
        </button>
        <button
          type="button"
          onClick={() => { setSelectedIds(new Set(events.map((e) => e.id))); setSelectAllMatching(false); }}
          disabled={events.length === 0}
          className="px-3 py-1.5 text-sm rounded-md border border-border hover:border-muted-foreground/40 text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40"
        >{t("events.select_page")}</button>
      </div>
      <ReviewQueue
        onOpenEvent={(eventId) => void openEvent(eventId)}
        focusId={searchParams.get("review")}
        cameraId={cameraFilter || null}
      />
        <div className="mb-4"><ActivityFilterBar /></div>

      <div className="flex items-center gap-1 mb-3">
        {([
          { v: "alert", l: t("events.alerts") },
          { v: "detection", l: t("events.detections") },
          { v: "", l: t("events.everything") },
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
          {t("events.tier_help")}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <select value={range} onChange={(e) => setRange(e.target.value as RangeValue)} className={selectClass} aria-label={t("events.time_range")}>
          {RANGES.map((r) => (
            <option key={r.value} value={r.value}>{r.label}</option>
          ))}
        </select>
        <select value={cameraFilter} onChange={(e) => setCameraFilter(e.target.value)} className={selectClass} aria-label={t("events.camera_filter")}>
          <option value="">{t("events.all_cameras")}</option>
          {cameras.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <select value={ruleFilter} onChange={(e) => setRuleFilter(e.target.value)} className={selectClass} aria-label={t("events.rule_filter")}>
          <option value="">{t("events.all_rules")}</option>
          {rules.map((r) => (
            <option key={r.id} value={r.id}>{r.name}</option>
          ))}
        </select>
        <select value={ackedFilter} onChange={(e) => setAckedFilter(e.target.value as "" | "false" | "true")} className={selectClass} aria-label={t("events.review_state_filter")}>
          <option value="">{t("events.reviewed_and_unreviewed")}</option>
          <option value="false">{t("events.unreviewed_only")}</option>
          <option value="true">{t("events.reviewed_only")}</option>
        </select>
      </div>

      {(selectedIds.size > 0 || selectAllMatching) && (
        <div className="flex flex-wrap items-center gap-2 mb-4 rounded-md border border-accent/30 bg-accent/5 px-3 py-2">
          <span className="text-xs text-accent">{selectAllMatching ? t("events.all_matching") : t("events.selected", { count: selectedIds.size })}</span>
          <button type="button" onClick={downloadSelectedCsv} disabled={bulkBusy} className="px-2 py-1 text-xs rounded border border-accent text-accent">{t("events.download_csv_short")}</button>
          <button type="button" onClick={bulkDelete} disabled={bulkBusy} className="px-2 py-1 text-xs rounded border border-red-500/50 text-red-400">{bulkBusy ? t("events.deleting") : t("events.delete")}</button>
          <button type="button" onClick={() => { setSelectedIds(new Set()); setSelectAllMatching(false); }} className="px-2 py-1 text-xs text-muted-foreground">{t("events.clear")}</button>
        </div>
      )}
      {events.length > 0 && selectedIds.size === events.length && !selectAllMatching && hasMore && (
        <div className="mb-4 rounded-md border border-accent/30 bg-accent/5 px-3 py-2 text-xs text-accent flex items-center justify-between">
          <span>{t("events.all_loaded_selected")}</span>
          <button type="button" onClick={() => setSelectAllMatching(true)} className="underline">{t("events.select_all_matching")}</button>
        </div>
      )}
      {bulkMessage && <div className="mb-4 rounded-md border border-border bg-muted px-3 py-2 text-xs text-muted-foreground">{bulkMessage}</div>}

      {error && (
        <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-muted-foreground py-12 text-center">{t("events.loading")}</p>
      ) : events.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border py-12 text-center">
          <p className="text-sm text-muted-foreground">
            {t("events.empty")}
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
                onClick={() => void openEvent(ev.id)}
                className="rounded-md border border-border bg-card p-3 cursor-pointer hover:border-muted-foreground/30 transition-colors"
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <input
                    type="checkbox"
                    checked={selectedIds.has(ev.id) || selectAllMatching}
                    onClick={(e) => e.stopPropagation()}
                    onChange={() => {
                      setSelectAllMatching(false);
                      setSelectedIds((prev) => {
                        const next = new Set(prev);
                        if (next.has(ev.id)) next.delete(ev.id); else next.add(ev.id);
                        return next;
                      });
                    }}
                    aria-label={t("events.select_event", { time: formatDateTime(ev.fired_at) })}
                    className="accent-[var(--accent)]"
                  />
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
                    {ev.rule_id ? ruleNames.get(ev.rule_id) || t("events.deleted_rule") : t("events.rule")}
                  </span>
                  {cameraOf(ev) && (
                    <span className="px-1.5 py-0.5 text-[10px] rounded bg-muted text-muted-foreground">
                      {cameraOf(ev)}
                    </span>
                  )}
                  {acked && (
                    <span className="px-1.5 py-0.5 text-[10px] rounded bg-green-500/15 text-green-400 border border-green-500/30">
                      ✓ {t("events.reviewed")}{ev.acked_via ? ` (${ev.acked_via})` : ""}
                    </span>
                  )}
                  {muted && (
                    <span className="px-1.5 py-0.5 text-[10px] rounded bg-muted text-muted-foreground">
                      🔕 {t("events.muted")}
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
                          ✓ {t("events.acknowledge")}
                        </button>
                      )}
                      {!muted && (
                        <button
                          type="button"
                          onClick={() => mute(ev.id)}
                          className="px-2 py-1 text-[11px] rounded-md border border-border text-muted-foreground hover:text-foreground hover:border-muted-foreground/40 transition-colors"
                          title={t("events.snooze_title")}
                        >
                          🔕 {t("events.mute_10m")}
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => setShareEvent(ev)}
                        className="px-2 py-1 text-[11px] rounded-md border border-border text-muted-foreground hover:text-foreground hover:border-muted-foreground/40 transition-colors"
                          title={t("events.share_title")}
                      >
                        🔗 {t("events.share")}
                      </button>
                      {ev.action_status === "failed" && ev.action_error && (
                        <span className="text-[11px] text-red-400 truncate">{ev.action_error}</span>
                      )}
                    </div>
                    {ev.payload ? (
                      <EventEvidence
                        payload={ev.payload}
                        recordingId={ev.recording_id}
                        isAdmin={user?.role === "admin"}
                        cameraId={String((ev.payload as Record<string, unknown>).camera_id || "")}
                        firedAt={ev.fired_at}
                        eventId={ev.id}
                      />
                    ) : (
                      <p className="text-[11px] text-muted-foreground">{t("events.no_payload")}</p>
                    )}
                    <EventFeedbackPanel eventId={ev.id} />
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
              {loadingMore ? t("events.loading") : t("events.load_more")}
            </button>
          )}
        </div>
      )}

      {shareEvent && (
        <ShareDialog
          kind="event"
          resourceId={shareEvent.id}
          label={[
            shareEvent.rule_id ? ruleNames.get(shareEvent.rule_id) || t("events.rule") : t("events.title"),
            cameraOf(shareEvent),
            formatDateTime(shareEvent.fired_at),
          ]
            .filter(Boolean)
            .join(" · ")}
          onClose={() => setShareEvent(null)}
        />
      )}
    </div>
  );
}
