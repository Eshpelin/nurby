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
}

function percent(value: number | null): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

export function AlertQualityCard() {
  const { authFetch, user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
  const [summary, setSummary] = useState<FeedbackSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    authFetch("/api/events/feedback/summary?hours=168")
      .then(async (res) => {
        if (!res.ok) return null;
        return await res.json() as FeedbackSummary;
      })
      .then((data) => {
        if (!cancelled) setSummary(data);
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
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
              <div><div className="text-muted-foreground">{t("alert_quality.fired")}</div><div className="font-medium">{summary.events_fired}</div></div>
              <div><div className="text-muted-foreground">{t("alert_quality.reviewed")}</div><div className="font-medium">{summary.events_reviewed} ({percent(summary.response_rate)})</div></div>
              <div><div className="text-muted-foreground">{t("alert_quality.nuisance")}</div><div className="font-medium">{summary.nuisance_alerts}</div></div>
              <div><div className="text-muted-foreground">{t("alert_quality.nuisance_rate")}</div><div className="font-medium">{percent(summary.nuisance_rate_reviewed)}</div></div>
            </div>
            <p className="mt-3 text-[11px] text-muted-foreground">
              {t("alert_quality.explanation", { firedRate: percent(summary.nuisance_rate_fired) })}
            </p>
          </>
        ) : (
          <p className="text-xs text-muted-foreground">{t("alert_quality.unavailable")}</p>
        )}
      </div>
    </div>
  );
}

export default AlertQualityCard;
