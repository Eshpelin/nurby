"use client";

// Left-rail run history. Shows the user's last 50 AgentRuns with a
// status pill and a cost number. Collapses to a drawer on mobile so
// the composer keeps the screen real estate. Defensive against a
// missing /api/agent/runs route.

import { useEffect, useState, useCallback } from "react";
import { useAuth } from "@/lib/auth";
import type { AgentRunSummary, RunStatus } from "./types";

interface ChatHistoryProps {
  selectedRunId: string | null;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  refreshKey?: number;
}

const STATUS_PILL: Record<RunStatus, string> = {
  running: "bg-blue-500/20 text-blue-300 border-blue-500/30",
  completed: "bg-green-500/20 text-green-400 border-green-500/30",
  failed: "bg-red-500/20 text-red-400 border-red-500/30",
  cancelled: "bg-zinc-500/20 text-zinc-300 border-zinc-500/30",
  budget_exhausted: "bg-amber-500/20 text-amber-300 border-amber-500/30",
};

function timeAgo(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const diff = Math.max(0, Date.now() - t);
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d`;
}

function fmtCents(c: number): string {
  return `$${(c / 100).toFixed(2)}`;
}

export default function ChatHistory({
  selectedRunId,
  onSelect,
  onNewChat,
  refreshKey = 0,
}: ChatHistoryProps) {
  const { authFetch } = useAuth();
  const [runs, setRuns] = useState<AgentRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [backendMissing, setBackendMissing] = useState(false);

  const fetchRuns = useCallback(async () => {
    try {
      const res = await authFetch("/api/agent/runs?limit=50");
      if (res.status === 404) {
        setBackendMissing(true);
        setRuns([]);
        return;
      }
      if (res.ok) {
        const data = await res.json();
        const list: AgentRunSummary[] = Array.isArray(data) ? data : data.runs ?? [];
        setRuns(list);
        setBackendMissing(false);
      }
    } catch {
      /* keep current */
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns, refreshKey]);

  // Light polling so a currently-running row updates its status pill
  // without forcing the parent to thread refresh tokens through.
  useEffect(() => {
    const t = setInterval(fetchRuns, 8000);
    return () => clearInterval(t);
  }, [fetchRuns]);

  return (
    <aside className="flex flex-col h-full w-72 border-r border-border bg-card/40">
      <div className="p-3 border-b border-border">
        <button
          type="button"
          onClick={onNewChat}
          aria-label="New chat"
          className="w-full px-3 py-2 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90 flex items-center justify-center gap-2"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
          New chat
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="p-3 space-y-2">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="h-12 rounded bg-muted/50 animate-pulse" />
            ))}
          </div>
        ) : backendMissing ? (
          <div className="p-4 text-xs text-muted-foreground">
            Agent backend not yet deployed. History will appear once /api/agent/runs is live.
          </div>
        ) : runs.length === 0 ? (
          <div className="p-4 text-xs text-muted-foreground">
            No questions yet. Ask one to get started.
          </div>
        ) : (
          <ul className="py-1">
            {runs.map((r) => {
              const active = r.id === selectedRunId;
              return (
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(r.id)}
                    className={`w-full text-left px-3 py-2 hover:bg-muted/60 transition-colors ${active ? "bg-muted" : ""}`}
                  >
                    <div className="text-xs font-medium line-clamp-2">{r.question}</div>
                    <div className="mt-1 flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
                      <div className="flex items-center gap-1.5">
                        <span className={`px-1.5 py-px rounded border ${STATUS_PILL[r.status] || ""}`}>
                          {r.status === "budget_exhausted" ? "budget" : r.status}
                        </span>
                        <span>{timeAgo(r.started_at)}</span>
                      </div>
                      <span className="font-mono">{fmtCents(r.cost_cents)}</span>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}
