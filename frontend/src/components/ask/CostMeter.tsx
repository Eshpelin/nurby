"use client";

// Daily-cost chip with a tiny progress bar. Click expands a popover
// listing today's per-run breakdown so a user investigating a surprise
// bill can see where the cents went.

import { useEffect, useRef, useState } from "react";
import type { UsageToday } from "./types";

interface CostMeterProps {
  usage: UsageToday | null;
  loading?: boolean;
}

function fmtCents(c: number): string {
  // Non-finite (missing/NaN from the usage API, common on a free local
  // model) reads as $0.00, not a confusing "$?.??".
  if (!Number.isFinite(c)) return "$0.00";
  return `$${(c / 100).toFixed(2)}`;
}

export default function CostMeter({ usage, loading }: CostMeterProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  if (loading || !usage) {
    return (
      <div className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md border border-border bg-background">
        <span className="inline-block w-20 h-3 bg-muted rounded animate-pulse" />
      </div>
    );
  }

  const pct = usage.cost_cents_cap > 0
    ? Math.min(100, (usage.cost_cents / usage.cost_cents_cap) * 100)
    : 0;
  let barColor = "bg-green-500";
  let textColor = "text-muted-foreground";
  if (pct >= 100) { barColor = "bg-red-500"; textColor = "text-red-400"; }
  else if (pct >= 80) { barColor = "bg-amber-500"; textColor = "text-amber-400"; }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={`Cost today: ${fmtCents(usage.cost_cents)} of ${fmtCents(usage.cost_cents_cap)}`}
        className="inline-flex items-center gap-2 px-2.5 py-1 text-xs rounded-md border border-border bg-background hover:bg-muted transition-colors"
      >
        <span className={`font-mono ${textColor}`}>
          {Number.isFinite(usage.cost_cents_cap) && usage.cost_cents_cap > 0
            ? `${fmtCents(usage.cost_cents)} / ${fmtCents(usage.cost_cents_cap)} today`
            : `${fmtCents(usage.cost_cents)} today`}
        </span>
        <span className="w-16 h-1.5 rounded-full bg-muted overflow-hidden">
          <span className={`block h-full ${barColor} transition-all`} style={{ width: `${pct}%` }} />
        </span>
      </button>
      {open && (
        <div className="absolute bottom-full mb-2 left-0 z-50 w-80 max-h-80 overflow-auto rounded-lg border border-border bg-card shadow-xl p-3 space-y-2">
          <div className="text-xs font-semibold">Today&apos;s spend</div>
          <div className="text-[11px] text-muted-foreground">
            {usage.runs} run{usage.runs !== 1 ? "s" : ""} ·{" "}
            {usage.tokens.toLocaleString()} tokens
          </div>
          {(!usage.per_run || usage.per_run.length === 0) ? (
            <div className="text-[11px] text-muted-foreground italic">No runs yet today.</div>
          ) : (
            <div className="space-y-1 mt-1">
              {usage.per_run.map((r) => (
                <div key={r.run_id} className="flex items-baseline justify-between gap-2 text-[11px]">
                  <span className="truncate">{r.question}</span>
                  <span className="font-mono text-muted-foreground whitespace-nowrap">{fmtCents(r.cost_cents)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
