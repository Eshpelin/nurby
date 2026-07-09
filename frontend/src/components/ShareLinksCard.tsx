"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import {
  ShareRow,
  SHARE_KIND_LABEL,
} from "@/app/settings/settings-helpers";

const STATUS_STYLE: Record<ShareRow["status"], string> = {
  active: "text-green-500",
  expired: "text-muted-foreground",
  revoked: "text-muted-foreground line-through",
  exhausted: "text-yellow-500",
};

function fmt(ts: string | null): string {
  if (!ts) return "—";
  return new Date(ts).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Settings card listing the anonymous share links this user created,
 * with per-row revoke. The raw link is never re-shown (only its hash is
 * stored server-side); this is purely an audit/kill-switch surface. */
export function ShareLinksCard() {
  const { authFetch } = useAuth();
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<ShareRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await authFetch("/api/shares");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setRows(await res.json());
    } catch {
      setError("Could not load share links.");
    }
  }, [authFetch]);

  useEffect(() => {
    if (open && rows === null) void load();
  }, [open, rows, load]);

  const revoke = async (id: string) => {
    setBusyId(id);
    try {
      const res = await authFetch(`/api/shares/${id}/revoke`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await load();
    } catch {
      setError("Could not revoke the link.");
    } finally {
      setBusyId(null);
    }
  };

  const activeCount = rows?.filter((r) => r.status === "active").length;

  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        onClick={() => setOpen(!open)}
        className="w-full px-4 py-3.5 flex items-center justify-between text-left"
      >
        <div className="flex items-center gap-3">
          <span
            className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
              activeCount ? "bg-green-500" : "bg-muted-foreground/40"
            }`}
          />
          <div>
            <div className="text-sm font-medium">Share links</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              {rows === null
                ? "Anonymous links you created for recordings, frames and events"
                : activeCount
                  ? `${activeCount} active link${activeCount === 1 ? "" : "s"}`
                  : "No active links"}
            </div>
          </div>
        </div>
        <span className="text-muted-foreground text-xs">
          {open ? "▲" : "▼"}
        </span>
      </button>

      {open && (
        <div className="px-4 pb-4 border-t border-border pt-3 space-y-2">
          {error && <div className="text-xs text-red-500">{error}</div>}
          {rows !== null && rows.length === 0 && (
            <div className="text-xs text-muted-foreground">
              Nothing shared yet. Use the Share button on a recording or
              event to create an anonymous link.
            </div>
          )}
          {rows?.map((r) => (
            <div
              key={r.id}
              className="flex items-center justify-between gap-3 text-sm"
            >
              <div className="min-w-0">
                <div className="truncate">
                  <span className="text-muted-foreground">
                    {SHARE_KIND_LABEL[r.kind]}
                  </span>{" "}
                  {r.label || "Untitled"}
                </div>
                <div className="text-xs text-muted-foreground font-mono mt-0.5">
                  <span className={STATUS_STYLE[r.status]}>{r.status}</span>
                  {" · "}
                  {r.view_count}
                  {r.max_views ? `/${r.max_views}` : ""} views
                  {" · expires "}
                  {fmt(r.expires_at)}
                </div>
              </div>
              {r.status === "active" && (
                <button
                  onClick={() => revoke(r.id)}
                  disabled={busyId === r.id}
                  className="px-2.5 py-1 rounded-md border border-border text-xs hover:bg-muted transition-colors disabled:opacity-50 flex-shrink-0"
                >
                  {busyId === r.id ? "Revoking…" : "Revoke"}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
