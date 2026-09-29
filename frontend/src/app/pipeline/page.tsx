"use client";

/**
 * Pipeline page. Fleet-wide view of the VLM (perception) backlog.
 *
 * The per-camera badges on the dashboard tell you a single camera is
 * slow. They cannot answer the question this page exists for: with N
 * cameras feeding one shared VLM, where is the whole backlog right now,
 * how fast are we draining it, and when will everything be caught up?
 *
 * Data comes from GET /api/system/pipeline-summary, which computes the
 * *serial* fleet ETA (cameras contend for one worker, so drain times add
 * up, they don't overlap). We poll every few seconds and also refetch on
 * any vlm_status WS event so the numbers stay live without a bespoke
 * aggregate socket.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useWSSubscribe } from "@/lib/ws";
import { translate } from "@/lib/i18n";

interface CameraRow {
  camera_id: string;
  camera_name: string;
  backlog: number;
  backlog_high: number;
  avg_latency: number;
  last_latency: number;
  eta_seconds: number;
  status: string;
  total_dropped: number;
  total_errors: number;
  reason: string;
}

interface PipelineSummary {
  health: "clear" | "catching_up" | "backlogged" | "degraded";
  total_queued: number;
  total_high_priority: number;
  fleet_eta_seconds: number;
  sec_per_frame: number;
  frames_per_min: number;
  camera_count: number;
  total_errors: number;
  status_counts: Record<string, number>;
  cameras: CameraRow[];
}

const POLL_MS = 5000;

/** Compact human duration: 45s, 3m 20s, 1h 4m. */
function fmtDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return "0s";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return rem ? `${m}m ${rem}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const remM = m % 60;
  return remM ? `${h}h ${remM}m` : `${h}h`;
}

const HEALTH_KEY: Record<PipelineSummary["health"], string> = {
  clear: "pipeline.health.clear",
  catching_up: "pipeline.health.catching_up",
  backlogged: "pipeline.health.backlogged",
  degraded: "pipeline.health.degraded",
};

const HEALTH_TONE: Record<PipelineSummary["health"], string> = {
  clear: "border-emerald-500/30 bg-emerald-500/10 text-emerald-400",
  catching_up: "border-sky-500/30 bg-sky-500/10 text-sky-400",
  backlogged: "border-amber-500/30 bg-amber-500/10 text-amber-400",
  degraded: "border-red-500/30 bg-red-500/10 text-red-400",
};

function statusTone(status: string): string {
  switch (status) {
    case "stalled":
    case "failed":
      return "text-red-400";
    case "slow":
      return "text-amber-400";
    case "processing":
    case "refining":
    case "queued":
      return "text-sky-400";
    default:
      return "text-muted-foreground";
  }
}

export default function PipelinePage() {
  const { authFetch, user } = useAuth();
  const locale = user?.locale;
  const t = (key: string, values?: Record<string, string | number>) =>
    translate(locale, key, values);
  const [data, setData] = useState<PipelineSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  // Coalesce the WS-triggered and interval-triggered refetches so a burst
  // of vlm_status events can't stampede the endpoint.
  const inFlight = useRef(false);

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const res = await authFetch("/api/system/pipeline-summary");
      if (res.ok) {
        setData(await res.json());
        setError(null);
      } else {
        setError(translate(locale, "pipeline.error_status", { status: res.status }));
      }
    } catch {
      setError(translate(locale, "pipeline.error"));
    } finally {
      inFlight.current = false;
      setLoaded(true);
    }
  }, [authFetch, locale]);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  // Any camera status change is a hint the aggregate moved. Refetch, but
  // let the in-flight guard debounce a burst down to one call.
  useWSSubscribe("vlm_status", () => {
    load();
  });

  return (
    <div className="max-w-5xl mx-auto p-6">
      <div className="flex items-center justify-between mb-1">
        <h1 className="text-2xl font-semibold tracking-tight">Pipeline</h1>
        {data && (
          <span
            className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${HEALTH_TONE[data.health]}`}
          >
            {t(HEALTH_KEY[data.health])}
          </span>
        )}
      </div>
      <p className="text-sm text-muted-foreground mb-5">
        {t("pipeline.description")}
      </p>

      {error && (
        <div className="mb-4 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-400">
          {error}
        </div>
      )}

      {!loaded ? (
        <div className="text-sm text-muted-foreground">{t("common.loading")}</div>
      ) : !data || data.camera_count === 0 ? (
        <div className="rounded-lg border border-border bg-card p-8 text-center text-sm text-muted-foreground">
          {t("pipeline.empty")}
        </div>
      ) : (
        <>
          {/* KPI strip */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <Kpi
              label={t("pipeline.frames_queued")}
              value={data.total_queued.toString()}
              hint={
                data.total_high_priority > 0
                  ? t("pipeline.high_priority", { count: data.total_high_priority })
                  : t("pipeline.all_cameras")
              }
              tone={data.total_queued > 30 ? "warn" : "normal"}
            />
            <Kpi
              label={t("pipeline.time_to_clear")}
              value={fmtDuration(data.fleet_eta_seconds)}
              hint={t("pipeline.shared_vlm")}
              tone={data.fleet_eta_seconds > 120 ? "warn" : "normal"}
            />
            <Kpi
              label={t("pipeline.current_rate")}
              value={data.sec_per_frame > 0 ? `${data.sec_per_frame}s` : "—"}
              hint={t("pipeline.per_frame")}
            />
            <Kpi
              label={t("pipeline.throughput")}
              value={
                data.frames_per_min > 0 ? `${data.frames_per_min}` : "—"
              }
              hint={t("pipeline.frames_per_min")}
            />
          </div>

          {/* Per-camera table, worst backlog first */}
          <div className="rounded-lg border border-border bg-card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground text-left">
                  <th className="font-medium px-4 py-2.5">{t("pipeline.camera")}</th>
                  <th className="font-medium px-3 py-2.5 text-right">{t("pipeline.backlog")}</th>
                  <th className="font-medium px-3 py-2.5 text-right">{t("pipeline.latency")}</th>
                  <th className="font-medium px-3 py-2.5 text-right">{t("pipeline.eta")}</th>
                  <th className="font-medium px-3 py-2.5 text-right">{t("pipeline.dropped")}</th>
                  <th className="font-medium px-4 py-2.5">{t("pipeline.status")}</th>
                </tr>
              </thead>
              <tbody>
                {data.cameras.map((c) => (
                  <tr
                    key={c.camera_id}
                    className="border-b border-border/50 last:border-0"
                  >
                    <td className="px-4 py-2.5 font-medium truncate max-w-[12rem]">
                      {c.camera_name}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums">
                      {c.backlog > 0 ? (
                        <span
                          className={c.backlog > 20 ? "text-amber-400" : ""}
                        >
                          {c.backlog}
                          {c.backlog_high > 0 && (
                            <span className="text-sky-400 text-xs ml-1">
                              ({c.backlog_high}!)
                            </span>
                          )}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">0</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-muted-foreground">
                      {c.avg_latency > 0 ? `${c.avg_latency}s` : "—"}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-muted-foreground">
                      {c.backlog > 0 ? fmtDuration(c.eta_seconds) : "—"}
                    </td>
                    <td className="px-3 py-2.5 text-right tabular-nums text-muted-foreground">
                      {c.total_dropped || "—"}
                    </td>
                    <td className={`px-4 py-2.5 ${statusTone(c.status)}`}>
                      {t(`pipeline.status.${c.status}`)}
                      {c.reason && (
                        <span className="text-xs text-muted-foreground ml-1">
                          · {c.reason}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="mt-3 text-xs text-muted-foreground">
            {t("pipeline.footnote")}
          </p>
        </>
      )}
    </div>
  );
}

function Kpi({
  label,
  value,
  hint,
  tone = "normal",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "normal" | "warn";
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div
        className={`mt-1 text-2xl font-semibold tabular-nums ${
          tone === "warn" ? "text-amber-400" : ""
        }`}
      >
        {value}
      </div>
      {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}
