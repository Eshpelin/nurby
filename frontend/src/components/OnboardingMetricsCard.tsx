"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

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
  const { authFetch } = useAuth();
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
      setError("Could not load onboarding metrics.");
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <p role="status" className="text-sm text-muted-foreground">Loading onboarding metrics…</p>;
  if (error) return <p role="alert" className="text-sm text-red-500">{error}</p>;
  if (!data) return null;

  const stat = (label: string, value: string) => (
    <div className="rounded-lg border border-border p-2">
      <div className="text-lg font-semibold">{value}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  );

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {stat("With a goal", String(data.users_with_preferences))}
      {stat("Configured", String(data.configured_count))}
      {stat("Verified", String(data.verified_count))}
      {stat("Verified rate", pct(data.verified_rate))}
      {stat("Median to first useful", minutes(data.median_seconds_to_first_useful))}
      {stat("Abandoned (7d+)", String(data.abandoned_count))}
      {stat("Synthetic-only", String(data.synthetic_only_count))}
      {stat("Paused", String(data.paused_count))}
    </div>
  );
}
