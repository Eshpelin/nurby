"use client";

/**
 * Household mode (#184): home, away or night, for the whole house.
 *
 * Rules gate on it, so this control is the difference between "alerts all
 * day" and "alerts that matter". It says what the current mode silences,
 * because a quiet rule is otherwise indistinguishable from a broken one.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/feedback";
import { timeAgo } from "@/lib/time";
import type { HouseholdMode, HouseholdModeState } from "@/lib/household-mode";

export function HouseholdModeControl({ compact = false }: { compact?: boolean }) {
  const { authFetch } = useAuth();
  const toast = useToast();
  const [state, setState] = useState<HouseholdModeState | null>(null);
  const [saving, setSaving] = useState<HouseholdMode | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await authFetch("/api/household/mode");
      if (r.ok) setState(await r.json());
    } catch {
      /* silent. The control just does not render. */
    }
  }, [authFetch]);

  useEffect(() => {
    load();
  }, [load]);

  const choose = async (mode: HouseholdMode) => {
    if (!state || mode === state.mode || saving) return;
    setSaving(mode);
    // Optimistic: the chip should move under the finger, not after a round trip.
    const previous = state;
    setState({ ...state, mode });
    try {
      const r = await authFetch("/api/household/mode", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode }),
      });
      if (!r.ok) throw new Error(await r.text());
      setState(await r.json());
    } catch {
      setState(previous);
      toast.error("Could not change the mode. Check the connection to the server.");
    } finally {
      setSaving(null);
    }
  };

  if (!state) return null;

  const active = state.modes.find((m) => m.key === state.mode);

  return (
    <div className={compact ? "" : "rounded-lg border border-border bg-card/50 p-3"}>
      <div className="flex items-center justify-between gap-3 mb-2">
        <span className="text-xs font-medium text-muted-foreground">Household</span>
        {state.since && (
          <span className="text-[10px] text-muted-foreground">
            since {timeAgo(state.since)}
          </span>
        )}
      </div>

      <div className="flex gap-1.5" role="group" aria-label="Household mode">
        {state.modes.map((m) => {
          const on = m.key === state.mode;
          return (
            <button
              key={m.key}
              type="button"
              onClick={() => choose(m.key)}
              disabled={saving != null}
              aria-pressed={on}
              title={m.hint}
              className={`flex-1 px-2.5 py-1.5 text-xs rounded-md border transition-colors disabled:opacity-60 ${
                on
                  ? "border-green-500/60 bg-green-500/15 text-green-300 font-medium"
                  : "border-border text-muted-foreground hover:bg-muted"
              }`}
            >
              {m.label}
            </button>
          );
        })}
      </div>

      <p className="text-[11px] text-muted-foreground mt-2">
        {active?.hint}
      </p>

      {state.silenced_rule_count > 0 && (
        <Link
          href="/rules"
          className="text-[11px] text-sky-300 hover:underline mt-1 inline-block"
        >
          {state.silenced_rule_count} rule
          {state.silenced_rule_count === 1 ? " is" : "s are"} paused while {active?.label}
        </Link>
      )}
    </div>
  );
}
