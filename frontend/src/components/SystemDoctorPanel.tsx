"use client";

// Settings section that runs GET /api/system/doctor and renders the
// structured verdicts. The answer to "why isn't this working?" without
// docker logs.

import { useState } from "react";
import { useAuth } from "@/lib/auth";

interface DoctorCheck {
  id: string;
  label: string;
  status: "ok" | "warn" | "fail" | "skip";
  detail: string;
  hint: string | null;
  latency_ms: number | null;
}

const STATUS_STYLE: Record<DoctorCheck["status"], { icon: string; cls: string }> = {
  ok: { icon: "✓", cls: "text-emerald-400" },
  warn: { icon: "!", cls: "text-amber-400" },
  fail: { icon: "✕", cls: "text-red-400" },
  skip: { icon: "–", cls: "text-muted-foreground" },
};

export function SystemDoctorPanel() {
  const { authFetch } = useAuth();
  const [checks, setChecks] = useState<DoctorCheck[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await authFetch("/api/system/doctor");
      if (!res.ok) throw new Error(`status ${res.status}`);
      setChecks(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Doctor run failed");
    } finally {
      setBusy(false);
    }
  };

  const failing = checks?.filter((c) => c.status === "fail").length ?? 0;
  const warning = checks?.filter((c) => c.status === "warn").length ?? 0;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          Checks the database, Redis, stream relay, every camera, every AI
          provider, email config and disk space, with a fix hint per problem.
        </p>
        <button
          type="button"
          onClick={run}
          disabled={busy}
          className="px-3 py-1.5 text-xs rounded-md bg-foreground text-background font-medium hover:opacity-90 disabled:opacity-50 flex-shrink-0 ml-3"
        >
          {busy ? "Checking." : checks ? "Run again" : "Run checks"}
        </button>
      </div>

      {error && <p className="text-xs text-red-400">{error}</p>}

      {checks && (
        <div className="space-y-1">
          <p className="text-xs text-muted-foreground">
            {failing === 0 && warning === 0
              ? "Everything looks healthy."
              : `${failing} failing, ${warning} warning${warning === 1 ? "" : "s"}.`}
          </p>
          {checks.map((c) => {
            const s = STATUS_STYLE[c.status];
            return (
              <div
                key={c.id}
                className="flex items-start gap-2.5 rounded-md border border-border/60 bg-background/40 px-2.5 py-1.5 text-xs"
              >
                <span className={`font-mono font-bold w-3 flex-shrink-0 ${s.cls}`}>{s.icon}</span>
                <div className="min-w-0">
                  <span className="font-medium">{c.label}</span>
                  <span className="text-muted-foreground"> — {c.detail}</span>
                  {c.latency_ms != null && (
                    <span className="text-muted-foreground/60"> ({c.latency_ms}ms)</span>
                  )}
                  {c.hint && c.status !== "ok" && (
                    <div className="text-[11px] text-amber-300/80 mt-0.5">{c.hint}</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default SystemDoctorPanel;
