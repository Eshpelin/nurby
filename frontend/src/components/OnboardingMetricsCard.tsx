"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";

interface OnboardingMetrics {
  users_with_preferences: number;
  goal_counts: Record<string, number>;
  place_counts: Record<string, number>;
  focus_counts: Record<string, number>;
  paused_count: number;
  configured_count: number;
  verified_count: number;
  verified_rate: number;
  abandoned_count: number;
  synthetic_only_count: number;
  median_seconds_to_first_useful: number | null;
  verified_by_goal: Record<string, number>;
  // First-run wizard funnel counters (#293). Optional: the field is
  // absent on responses from before the funnel existed.
  funnel?: Record<string, number>;
}

function pct(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

function minutes(seconds: number | null): string {
  if (seconds == null) return "—";
  return `${Math.round(seconds / 60)} min`;
}

// Admin-only, aggregate onboarding outcomes. Read-only. Its endpoint is
// admin-gated, so a non-admin never sees numbers here.
export function OnboardingMetricsCard() {
  const { authFetch, user } = useAuth();
  const locale = user?.locale;
  const t = (key: string, values?: Record<string, string | number>) => translate(locale, key, values);
  const [data, setData] = useState<OnboardingMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch("/api/auth/onboarding/metrics");
      if (!res.ok) throw new Error("load");
      setData(await res.json());
    } catch {
      setError(translate(locale, "onboarding_metrics.error"));
    } finally {
      setLoading(false);
    }
  }, [authFetch, locale]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <p role="status" className="text-sm text-muted-foreground">{t("onboarding_metrics.loading")}</p>;
  if (error) return <p role="alert" className="text-sm text-red-500">{error}</p>;
  if (!data) return null;

  const stat = (label: string, value: string, key?: string) => (
    <div key={key} className="rounded-lg border border-border p-2">
      <div className="text-lg font-semibold">{value}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  );

  const funnel = data.funnel ?? {};
  const funnelRow: Array<[string, number]> = [
    [t("onboarding_metrics.wizard_shown"), funnel.wizard_shown ?? 0],
    [t("onboarding_metrics.magic_clicked"), funnel.magic_clicked ?? 0],
    [t("onboarding_metrics.manual_clicked"), funnel.manual_clicked ?? 0],
    [t("onboarding_metrics.completed"), funnel.wizard_completed ?? 0],
  ];

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {stat(t("onboarding_metrics.with_goal"), String(data.users_with_preferences))}
        {stat(t("onboarding_metrics.configured"), String(data.configured_count))}
        {stat(t("onboarding_metrics.verified"), String(data.verified_count))}
        {stat(t("onboarding_metrics.verified_rate"), pct(data.verified_rate))}
        {stat(t("onboarding_metrics.median_useful"), minutes(data.median_seconds_to_first_useful))}
        {stat(t("onboarding_metrics.abandoned"), String(data.abandoned_count))}
        {stat(t("onboarding_metrics.synthetic_only"), String(data.synthetic_only_count))}
        {stat(t("onboarding_metrics.paused"), String(data.paused_count))}
      </div>
      {data.funnel !== undefined && (
        <div>
          <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide mb-1">
            {t("onboarding_metrics.funnel_title")}
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {funnelRow.map(([label, value]) => stat(label, String(value), label))}
          </div>
        </div>
      )}
    </div>
  );
}
