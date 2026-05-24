"use client";

// Admin-only household-wide AgentRuns view. Backend enforces auth;
// frontend hides the nav entry for non-admins as defense in depth.

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import type { AgentRunSummary, RunStatus } from "@/components/ask/types";

const STATUS_PILL: Record<RunStatus, string> = {
  running: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  completed: "bg-green-500/20 text-green-400 border-green-500/30",
  failed: "bg-red-500/20 text-red-400 border-red-500/30",
  cancelled: "bg-zinc-500/20 text-zinc-300 border-zinc-500/30",
  budget_exhausted: "bg-amber-500/20 text-amber-300 border-amber-500/30",
};

function fmtCents(c: number): string { return `$${(c / 100).toFixed(2)}`; }
function fmt(iso: string): string {
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

export default function AdminRunsPage() {
  const { authFetch, user } = useAuth();
  const router = useRouter();
  const [runs, setRuns] = useState<AgentRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user && user.role !== "admin") {
      router.replace("/ask");
    }
  }, [user, router]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await authFetch("/api/agent/admin/runs?limit=200");
        if (res.status === 404) { if (!cancelled) setError("Admin endpoint not yet deployed."); return; }
        if (res.status === 403) { if (!cancelled) setError("Admin access required."); return; }
        if (res.ok) {
          const data = await res.json();
          if (!cancelled) setRuns(Array.isArray(data) ? data : data.runs ?? []);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Network error.");
      } finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [authFetch]);

  return (
    <div className="max-w-6xl mx-auto px-6 py-6">
      <div className="flex items-baseline justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Ask Nurby · Admin runs</h1>
          <p className="text-sm text-muted-foreground mt-1">Household-wide audit view of every AgentRun.</p>
        </div>
        <Link href="/ask" className="text-xs text-muted-foreground hover:text-foreground">← Back to chat</Link>
      </div>
      {loading && <div className="text-sm text-muted-foreground">Loading.</div>}
      {error && <div className="text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded p-3">{error}</div>}
      {!loading && !error && (
        <div className="border border-border rounded-lg overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-card text-muted-foreground">
              <tr>
                <th className="text-left px-3 py-2 font-medium">User</th>
                <th className="text-left px-3 py-2 font-medium">Question</th>
                <th className="text-left px-3 py-2 font-medium">Status</th>
                <th className="text-right px-3 py-2 font-medium">Cost</th>
                <th className="text-left px-3 py-2 font-medium">Started</th>
                <th className="text-right px-3 py-2 font-medium">Latency</th>
              </tr>
            </thead>
            <tbody>
              {runs.length === 0 && (
                <tr><td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">No runs yet.</td></tr>
              )}
              {runs.map((r) => (
                <tr
                  key={r.id}
                  className="border-t border-border hover:bg-muted/40 cursor-pointer"
                  onClick={() => router.push(`/ask/runs/${r.id}`)}
                >
                  <td className="px-3 py-2">{r.user_display_name ?? r.user_id?.slice(0, 6) ?? "—"}</td>
                  <td className="px-3 py-2 max-w-md truncate">{r.question}</td>
                  <td className="px-3 py-2">
                    <span className={`px-1.5 py-px rounded border ${STATUS_PILL[r.status]}`}>{r.status}</span>
                  </td>
                  <td className="px-3 py-2 text-right font-mono">{fmtCents(r.cost_cents)}</td>
                  <td className="px-3 py-2 font-mono">{fmt(r.started_at)}</td>
                  <td className="px-3 py-2 text-right font-mono">{r.latency_ms ? `${r.latency_ms}ms` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
