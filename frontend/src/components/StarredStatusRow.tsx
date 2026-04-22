"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

interface StarredStatus {
  person_id: string;
  display_name: string;
  photo_path: string | null;
  status: string;
  last_seen_at: string | null;
  last_camera_id: string | null;
  last_thumbnail_path: string | null;
  sightings_24h: number;
  generated_at: string;
  cached: boolean;
}

function timeAgo(iso: string | null): string {
  if (!iso) return "no sightings";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function StarredStatusRow() {
  const { authFetch } = useAuth();
  const [items, setItems] = useState<StarredStatus[]>([]);
  const [refreshingId, setRefreshingId] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);

  const fetchStatus = useCallback(async (force = false) => {
    try {
      const res = await authFetch(`/api/persons/starred/status${force ? "?force=true" : ""}`);
      if (res.ok) setItems(await res.json());
    } catch {
      /* silent */
    }
  }, [authFetch]);

  useEffect(() => {
    fetchStatus();
    const t = setInterval(() => fetchStatus(), 120000);
    return () => clearInterval(t);
  }, [fetchStatus]);

  const refreshOne = useCallback(async (id: string) => {
    setRefreshingId(id);
    try {
      const res = await authFetch(`/api/persons/starred/status?force=true`);
      if (res.ok) setItems(await res.json());
    } finally {
      setRefreshingId(null);
    }
  }, [authFetch]);

  if (dismissed || items.length === 0) return null;

  return (
    <div className="flex-shrink-0 mb-3 rounded-lg border border-border bg-card/60 backdrop-blur-sm overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border/60">
        <div className="flex items-center gap-2">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" className="text-amber-400">
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
          </svg>
          <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Pinned people
          </span>
          <span className="text-[10px] text-muted-foreground/60">
            {items.length}
          </span>
        </div>
        <button
          onClick={() => setDismissed(true)}
          aria-label="Hide"
          className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>
      <div className="flex gap-2 overflow-x-auto p-2">
        {items.map((it) => (
          <div
            key={it.person_id}
            className="flex-shrink-0 w-[260px] rounded-md border border-border bg-background/60 p-2.5 hover:border-amber-500/30 transition-colors"
          >
            <div className="flex items-start gap-2.5">
              {it.photo_path ? (
                <img
                  src={`/api/persons/${it.person_id}/photo`}
                  alt={it.display_name}
                  className="w-9 h-9 rounded-full object-cover border border-border flex-shrink-0"
                />
              ) : (
                <div className="w-9 h-9 rounded-full bg-muted flex items-center justify-center text-xs font-medium flex-shrink-0">
                  {it.display_name.charAt(0).toUpperCase()}
                </div>
              )}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-sm font-medium truncate">
                    {it.display_name}
                  </span>
                  {it.cached && (
                    <span className="text-[9px] text-muted-foreground/60 font-mono">
                      cached
                    </span>
                  )}
                </div>
                <div className="text-[10px] text-muted-foreground">
                  {timeAgo(it.last_seen_at)}
                  {it.sightings_24h > 0 && (
                    <>
                      <span className="mx-1">&middot;</span>
                      {it.sightings_24h} today
                    </>
                  )}
                </div>
              </div>
              <button
                onClick={() => refreshOne(it.person_id)}
                disabled={refreshingId === it.person_id}
                aria-label="Refresh recap"
                title="Refresh recap"
                className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors disabled:opacity-40"
              >
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className={refreshingId === it.person_id ? "animate-spin" : ""}
                >
                  <polyline points="23 4 23 10 17 10" />
                  <polyline points="1 20 1 14 7 14" />
                  <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
                </svg>
              </button>
            </div>
            <p className="mt-2 text-xs leading-snug text-foreground/90 line-clamp-3">
              {it.status}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
