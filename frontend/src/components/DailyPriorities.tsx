"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";

interface DailyPriority {
  key: string;
  title: string;
  detail: string;
  href: string;
  blocked_reason: string | null;
}
interface DailyWorkflow {
  audience: "administrator" | "viewer" | "guardian";
  paused: boolean;
  place_label: string | null;
  priorities: DailyPriority[];
}

interface Props {
  // Bumped by the parent when preferences change, to refetch.
  refreshKey?: number;
  paused: boolean;
  onTogglePause: () => void;
  pauseBusy?: boolean;
}

const button = "rounded-lg border border-border px-3 py-2 text-sm hover:bg-muted/50 disabled:opacity-50";

// Read-only daily priorities for the person's audience and goal. It never
// changes a rule; pausing only quiets the nudges via the parent's save.
export function DailyPriorities({ refreshKey = 0, paused, onTogglePause, pauseBusy }: Props) {
  const { authFetch } = useAuth();
  const [wf, setWf] = useState<DailyWorkflow | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch("/api/auth/me/daily");
      if (!res.ok) throw new Error("load");
      setWf(await res.json());
    } catch {
      setError("Could not load today's priorities.");
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  if (loading) return <p role="status" className="mt-4 text-sm text-muted-foreground">Loading your priorities…</p>;
  if (error) return <p role="alert" className="mt-4 text-sm text-red-500">{error}</p>;
  if (!wf) return null;
  const priorities = wf.priorities ?? [];

  return (
    <section aria-label="Today's priorities" className="mt-4 rounded-lg border border-border p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Today{wf.place_label ? ` · ${wf.place_label}` : ""}</h3>
        <button className={button} disabled={pauseBusy} onClick={onTogglePause}>
          {paused ? "Resume daily guidance" : "Pause daily guidance"}
        </button>
      </div>
      <ul className="mt-3 space-y-2">
        {priorities.map((p) => (
          <li key={p.key} className="text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <Link href={p.href} className="font-medium underline-offset-2 hover:underline">{p.title}</Link>
              {p.blocked_reason && (
                <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-xs text-amber-600">{p.blocked_reason}</span>
              )}
            </div>
            <p className="text-xs text-muted-foreground">{p.detail}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
