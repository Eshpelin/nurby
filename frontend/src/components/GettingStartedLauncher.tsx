"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { PersonalOnboardingCard } from "@/components/PersonalOnboardingCard";
import { OnboardingMetricsCard } from "@/components/OnboardingMetricsCard";
import { DETECTION_GOALS, milestoneForGoal, type ActivationList } from "@/lib/activation";
import type { Experience } from "@/lib/onboarding";

interface Props {
  cameraCount: number;
  camerasLoading: boolean;
  onSetup: () => void;
  isAdmin: boolean;
}

// The launcher is a thin guidance layer, not a permanent dashboard widget:
// a corner pill that opens the setup content in a popover and quietly
// retires (mutes) once activation is verified. It never replaces navigation.
type Badge = {
  hidden: boolean;
  label: string;
  progress: string | null; // "1/3" while in progress
  complete: boolean; // retired to a muted state
};

const TOTAL_STEPS = 3;

function computeBadge(exp: Experience | null, acts: ActivationList | null): Badge {
  // Only administrators set the installation up. Viewers and guardians have
  // no multi-step onboarding, so they get no launcher at all.
  if (exp && exp.audience !== "administrator") {
    return { hidden: true, label: "", progress: null, complete: false };
  }
  const prefs = exp?.preferences ?? null;
  if (!prefs) {
    return { hidden: false, label: "Set up Nurby", progress: null, complete: false };
  }
  if (DETECTION_GOALS.has(prefs.goal)) {
    const m = milestoneForGoal(acts, prefs.goal);
    if (m?.verified) return { hidden: false, label: "Nurby set up", progress: null, complete: true };
    const done = m?.steps.filter((s) => s.done).length ?? 0;
    return { hidden: false, label: "Getting started", progress: `${done}/${TOTAL_STEPS}`, complete: false };
  }
  // review / explore: no verifiable activation, so treat as settled.
  return { hidden: false, label: "Nurby set up", progress: null, complete: true };
}

export function GettingStartedLauncher({ cameraCount, camerasLoading, onSetup, isAdmin }: Props) {
  const { authFetch } = useAuth();
  const [open, setOpen] = useState(false);
  const [badge, setBadge] = useState<Badge | null>(null);

  const refresh = useCallback(async () => {
    // Non-admins have no setup launcher, so don't even query for them.
    if (!isAdmin) return;
    try {
      const [expRes, actRes] = await Promise.all([
        authFetch("/api/auth/me/experience"),
        authFetch("/api/auth/me/activation"),
      ]);
      const exp: Experience | null = expRes.ok ? await expRes.json() : null;
      const acts: ActivationList | null = actRes.ok ? await actRes.json() : null;
      // If we could not load experience, keep an entry point for admins only.
      if (!exp) {
        setBadge({ hidden: false, label: "Set up Nurby", progress: null, complete: false });
        return;
      }
      setBadge(computeBadge(exp, acts));
    } catch {
      setBadge({ hidden: false, label: "Set up Nurby", progress: null, complete: false });
    }
  }, [authFetch, isAdmin]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (!isAdmin || !badge || badge.hidden) return null;

  const pill = badge.complete
    ? "border border-border bg-card text-muted-foreground hover:text-foreground"
    : "bg-accent text-white shadow-lg hover:opacity-90";

  return (
    <div className="fixed bottom-4 left-4 z-40 hidden sm:block">
      {open && (
        <div className="mb-2 w-[min(92vw,384px)] max-h-[75vh] overflow-y-auto rounded-xl border border-border bg-card-elevated shadow-xl p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold">{badge.complete ? "Your Nurby setup" : "Getting started"}</h2>
            <button aria-label="Close" onClick={() => setOpen(false)} className="text-muted-foreground hover:text-foreground text-lg leading-none">×</button>
          </div>
          <PersonalOnboardingCard
            embedded
            cameraCount={cameraCount}
            camerasLoading={camerasLoading}
            onSetup={() => { setOpen(false); onSetup(); }}
            onChanged={refresh}
          />
          {isAdmin && (
            <details className="mt-4 rounded-lg border border-border p-3">
              <summary className="cursor-pointer text-sm font-medium text-muted-foreground">Onboarding metrics</summary>
              <div className="mt-3"><OnboardingMetricsCard /></div>
            </details>
          )}
        </div>
      )}
      <button
        onClick={() => { const next = !open; setOpen(next); if (next) void refresh(); }}
        aria-expanded={open}
        className={`flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium ${pill}`}
      >
        <span aria-hidden>{badge.complete ? "✓" : "🚀"}</span>
        {badge.label}
        {badge.progress && (
          <span className="rounded-full bg-white/20 px-1.5 py-0.5 text-xs">{badge.progress}</span>
        )}
      </button>
    </div>
  );
}
