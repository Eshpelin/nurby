"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";

interface FeedbackSummary {
  window_hours: number;
  events_fired: number;
  events_reviewed: number;
  response_rate: number | null;
  nuisance_alerts: number;
  nuisance_rate_reviewed: number | null;
  nuisance_rate_fired: number | null;
  delivered_alerts: number;
  opened_alerts: number;
  open_rate_delivered: number | null;
  clip_opened_alerts: number;
  clip_open_rate_delivered: number | null;
  delivery_by_channel: {
    channel: string;
    delivered_alerts: number;
    opened_alerts: number;
    clip_opened_alerts: number;
  }[];
  nuisance_by_camera_day: {
    camera_id: string;
    day: string;
    reviewed: number;
    nuisance: number;
    nuisance_rate_reviewed: number | null;
  }[];
}

function percent(value: number | null): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

export function AlertQualityCard() {
  const { authFetch, user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
  const [summary, setSummary] = useState<FeedbackSummary | null>(null);
  const [cameraNames, setCameraNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      authFetch("/api/events/feedback/summary?hours=168"),
      authFetch("/api/cameras"),
    ])
      .then(async ([summaryResponse, cameraResponse]) => {
        if (summaryResponse.ok && !cancelled) setSummary(await summaryResponse.json() as FeedbackSummary);
        if (cameraResponse.ok && !cancelled) {
          const cameras = await cameraResponse.json();
          if (Array.isArray(cameras)) {
            setCameraNames(Object.fromEntries(cameras.map((camera: { id: string; name: string }) => [camera.id, camera.name])));
          }
        }
      })
      .catch(() => {
        if (!cancelled) setSummary(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch]);

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="px-4 py-3 flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium">{t("alert_quality.title")}</div>
          <div className="text-xs text-muted-foreground mt-0.5">{t("alert_quality.subtitle")}</div>
        </div>
        <Link href="/events" className="text-xs text-accent hover:underline whitespace-nowrap">
          {t("alert_quality.open_alerts")}
        </Link>
      </div>
      <div className="border-t border-border px-4 py-3">
        {loading ? (
          <p className="text-xs text-muted-foreground">{t("alert_quality.loading")}</p>
        ) : summary ? (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-6 gap-3 text-xs">
              <div><div className="text-muted-foreground">{t("alert_quality.fired")}</div><div className="font-medium">{summary.events_fired}</div></div>
              <div><div className="text-muted-foreground">{t("alert_quality.reviewed")}</div><div className="font-medium">{summary.events_reviewed} ({percent(summary.response_rate)})</div></div>
              <div><div className="text-muted-foreground">{t("alert_quality.nuisance")}</div><div className="font-medium">{summary.nuisance_alerts}</div></div>
              <div><div className="text-muted-foreground">{t("alert_quality.nuisance_rate")}</div><div className="font-medium">{percent(summary.nuisance_rate_reviewed)}</div></div>
              <div><div className="text-muted-foreground">{t("alert_quality.opened")}</div><div className="font-medium">{summary.opened_alerts}/{summary.delivered_alerts} ({percent(summary.open_rate_delivered)})</div></div>
              <div><div className="text-muted-foreground">{t("alert_quality.clip_opened")}</div><div className="font-medium">{summary.clip_opened_alerts}/{summary.delivered_alerts} ({percent(summary.clip_open_rate_delivered)})</div></div>
            </div>
            <p className="mt-3 text-[11px] text-muted-foreground">
              {t("alert_quality.explanation", { firedRate: percent(summary.nuisance_rate_fired) })}
            </p>
            {(summary.delivery_by_channel ?? []).length > 0 && (
              <div className="mt-3 border-t border-border pt-3">
                <div className="text-xs font-medium mb-1">{t("alert_quality.by_channel")}</div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
                  {summary.delivery_by_channel.map((row) => (
                    <span key={row.channel}>
                      {t("alert_quality.channel_stats", {
                        channel: row.channel,
                        delivered: row.delivered_alerts,
                        opened: row.opened_alerts,
                        clips: row.clip_opened_alerts,
                      })}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {(summary.nuisance_by_camera_day ?? []).length > 0 && (
              <div className="mt-3 border-t border-border pt-3">
                <div className="text-xs font-medium mb-1">{t("alert_quality.by_camera_day")}</div>
                <div className="space-y-1">
                  {(summary.nuisance_by_camera_day ?? []).slice(0, 5).map((row) => (
                    <div key={`${row.camera_id}-${row.day}`} className="flex justify-between gap-3 text-[11px] text-muted-foreground">
                      <span className="truncate">{cameraNames[row.camera_id] || (row.camera_id === "unscoped" ? t("alert_quality.unscoped") : row.camera_id)} · {row.day}</span>
                      <span className="shrink-0">{row.nuisance}/{row.reviewed} · {percent(row.nuisance_rate_reviewed)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        ) : (
          <p className="text-xs text-muted-foreground">{t("alert_quality.unavailable")}</p>
        )}
      </div>
    </div>
  );
}

export default AlertQualityCard;
