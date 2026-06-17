"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { timeAgo as timeAgoBase } from "@/lib/time";

interface StarredStatus {
  person_id: string;
  display_name: string;
  photo_path: string | null;
  status: string;
  last_seen_at: string | null;
  last_camera_id: string | null;
  last_camera_name: string | null;
  last_thumbnail_path: string | null;
  last_observation_id: string | null;
  sightings_24h: number;
  generated_at: string;
  cached: boolean;
  stale: boolean;
}

const timeAgo = (iso: string | null) => timeAgoBase(iso, { fallback: "no sightings" });

function Avatar({ it, size = "md" }: { it: StarredStatus; size?: "sm" | "md" }) {
  const { token } = useAuth();
  const dim = size === "sm" ? "h-7 w-7 text-[10px]" : "h-8 w-8 text-xs";
  if (it.photo_path) {
    return (
      <img
        src={`/api/persons/${it.person_id}/photo${token ? `?token=${token}` : ""}`}
        alt={it.display_name}
        className={`${dim} rounded-full object-cover ring-1 ring-border`}
      />
    );
  }
  return (
    <div className={`${dim} rounded-full bg-muted flex items-center justify-center font-medium ring-1 ring-border`}>
      {it.display_name.charAt(0).toUpperCase()}
    </div>
  );
}

interface NamedPerson {
  id: string;
  display_name: string;
  photo_path: string | null;
  is_starred: boolean;
}
interface UnknownCluster {
  id: string;
  sample_thumbnail_path: string | null;
  sighting_count: number;
}

export function StarredStatusRow() {
  const { authFetch, token } = useAuth();
  const [items, setItems] = useState<StarredStatus[]>([]);
  const [refreshingId, setRefreshingId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  // Empty-state discovery. people detected but not starred, and unnamed
  // face clusters awaiting a name. Drives a useful empty row instead of a
  // dead-end "no one to watch" message.
  const [people, setPeople] = useState<NamedPerson[] | null>(null);
  const [clusters, setClusters] = useState<UnknownCluster[] | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const fetchStatus = useCallback(async (force = false) => {
    try {
      const res = await authFetch(`/api/persons/starred/status${force ? "?force=true" : ""}`);
      if (res.ok) setItems(await res.json());
    } catch {
      /* silent */
    }
  }, [authFetch]);

  // When nobody is being watched, find out who HAS been detected so the
  // empty state can show them with name/star actions.
  const fetchDetected = useCallback(async () => {
    try {
      const [pRes, cRes] = await Promise.all([
        authFetch("/api/persons"),
        authFetch("/api/persons/suggestions"),
      ]);
      if (pRes.ok) setPeople(await pRes.json());
      else setPeople([]);
      if (cRes.ok) setClusters(await cRes.json());
      else setClusters([]);
    } catch {
      setPeople([]);
      setClusters([]);
    }
  }, [authFetch]);

  const starPerson = useCallback(async (id: string) => {
    try {
      await authFetch(`/api/persons/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_starred: true }),
      });
      await fetchStatus(true);
    } catch {
      /* silent */
    }
  }, [authFetch, fetchStatus]);

  useEffect(() => {
    fetchStatus();
    const t = setInterval(() => fetchStatus(), 120000);
    return () => clearInterval(t);
  }, [fetchStatus]);

  useEffect(() => {
    if (items.length === 0) fetchDetected();
  }, [items.length, fetchDetected]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    // The /ws socket is token-authenticated (issue #40); skip until a token
    // exists, reconnect (effect re-run) when it appears.
    if (!token) return;
    const apiBase = process.env.NEXT_PUBLIC_API_BASE || window.location.origin;
    const url = `${apiBase.replace(/^http/, "ws")}/ws?token=${encodeURIComponent(token)}`;
    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === "recap_stale" || msg.type === "person_seen") {
            fetchStatus();
          }
        } catch {
          /* ignore */
        }
      };
      ws.onerror = () => { /* silent */ };
    } catch {
      /* silent */
    }
    return () => {
      try { wsRef.current?.close(); } catch { /* ignore */ }
    };
  }, [fetchStatus, token]);

  const refreshOne = useCallback(async (id: string) => {
    setRefreshingId(id);
    try {
      const res = await authFetch(`/api/persons/starred/status?force=true`);
      if (res.ok) setItems(await res.json());
    } finally {
      setRefreshingId(null);
    }
  }, [authFetch]);

  if (items.length === 0) {
    const namedUnstarred = (people || []).filter((p) => !p.is_starred);
    const unknown = clusters || [];
    // Nothing detected yet (or still loading). show nothing rather than a
    // dead-end message. faces populate this as soon as they are seen.
    if ((people === null && clusters === null) || (namedUnstarred.length === 0 && unknown.length === 0)) {
      return null;
    }
    // People have been seen but none are starred. invite naming / starring.
    return (
      <div className="flex-shrink-0 mb-3 rounded-lg border border-border bg-card/40 px-3 py-2.5">
        <div className="flex items-center gap-2 mb-2">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" className="text-amber-400/80">
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
          </svg>
          <span className="text-[11px] font-medium">
            {namedUnstarred.length > 0 ? "Star people to watch them here" : "New faces detected"}
          </span>
          <a href="/people" className="ml-auto text-[11px] text-accent hover:underline">
            Manage in People →
          </a>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {namedUnstarred.slice(0, 6).map((p) => (
            <button
              key={p.id}
              onClick={() => starPerson(p.id)}
              title={`Watch ${p.display_name}`}
              className="group flex items-center gap-1.5 pl-1 pr-2 py-1 rounded-full border border-border bg-background hover:border-amber-500/50 transition-colors"
            >
              {p.photo_path ? (
                <img src={`/api/persons/${p.id}/photo${token ? `?token=${token}` : ""}`} alt="" className="h-6 w-6 rounded-full object-cover" />
              ) : (
                <span className="h-6 w-6 rounded-full bg-muted flex items-center justify-center text-[10px] font-medium">{p.display_name.charAt(0).toUpperCase()}</span>
              )}
              <span className="text-[11px] truncate max-w-[90px]">{p.display_name}</span>
              <span className="text-amber-400/70 group-hover:text-amber-400 text-xs leading-none">☆</span>
            </button>
          ))}
          {unknown.slice(0, 6).map((c) => (
            <a
              key={c.id}
              href="/people"
              title={`Unnamed. seen ${c.sighting_count}x. Click to name.`}
              className="flex items-center gap-1.5 pl-1 pr-2 py-1 rounded-full border border-dashed border-yellow-500/40 bg-yellow-500/5 hover:bg-yellow-500/10 transition-colors"
            >
              <img src={`/api/persons/suggestions/${c.id}/thumbnail${token ? `?token=${token}` : ""}`} alt="" className="h-6 w-6 rounded-full object-cover bg-muted" />
              <span className="text-[11px] text-yellow-300">Name? · {c.sighting_count}x</span>
            </a>
          ))}
        </div>
      </div>
    );
  }

  const active = items.filter((it) => it.last_observation_id && it.last_seen_at);
  const allQuiet = active.length === 0;

  // Quiet mode. One-line flat summary with overlapping avatars. Click to expand.
  if (allQuiet && !expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        className="flex-shrink-0 mb-3 w-full flex items-center gap-3 px-1 py-1.5 rounded hover:bg-muted/30 transition-colors text-left"
      >
        <div className="flex -space-x-2">
          {items.slice(0, 5).map((it) => (
            <div key={it.person_id} className="ring-2 ring-background rounded-full">
              <Avatar it={it} size="sm" />
            </div>
          ))}
        </div>
        <span className="text-xs text-muted-foreground">
          All quiet. Watching {items.length} {items.length === 1 ? "person" : "people"}.
        </span>
      </button>
    );
  }

  // Active mode. Flat horizontal ribbon, hairline dividers, no outer box.
  return (
    <div className="flex-shrink-0 mb-3">
      <div className="mb-2 flex items-center gap-2 px-1">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" className="text-amber-400">
          <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
        </svg>
        <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          Watching
        </span>
        <span className="text-[10px] text-muted-foreground/60">
          {items.length}
        </span>
        {allQuiet && (
          <button
            onClick={() => setExpanded(false)}
            className="ml-auto text-[11px] text-muted-foreground hover:text-foreground"
          >
            Collapse
          </button>
        )}
      </div>
      <div className="flex divide-x divide-border/60 overflow-x-auto">
        {items.map((it) => {
          const hasSighting = !!it.last_observation_id && !!it.last_seen_at;
          return (
            <div
              key={it.person_id}
              className="flex-shrink-0 w-[280px] flex gap-2.5 px-3 py-2 first:pl-1 group hover:bg-muted/20 transition-colors"
            >
              {hasSighting ? (
                <div className="relative flex-shrink-0 w-16 aspect-video rounded overflow-hidden bg-muted/20">
                  <img
                    src={`/api/observations/${it.last_observation_id}/thumbnail${token ? `?token=${token}` : ""}`}
                    alt=""
                    className="h-full w-full object-cover"
                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                  />
                </div>
              ) : (
                <div className="flex-shrink-0">
                  <Avatar it={it} />
                </div>
              )}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-[13px] font-medium truncate">
                    {it.display_name}
                  </span>
                  {it.stale && (
                    <span className="text-[9px] font-mono text-amber-400">stale</span>
                  )}
                  <button
                    onClick={() => refreshOne(it.person_id)}
                    disabled={refreshingId === it.person_id}
                    aria-label="Refresh recap"
                    className="ml-auto p-0.5 rounded text-muted-foreground/60 hover:text-foreground opacity-0 group-hover:opacity-100 transition-opacity disabled:opacity-40"
                  >
                    <svg
                      width="10"
                      height="10"
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
                <div className="text-[10px] text-muted-foreground truncate">
                  {hasSighting ? (
                    <>
                      {timeAgo(it.last_seen_at)}
                      {it.last_camera_name && (
                        <>
                          <span className="mx-1">&middot;</span>
                          {it.last_camera_name}
                        </>
                      )}
                      {it.sightings_24h > 0 && (
                        <>
                          <span className="mx-1">&middot;</span>
                          {it.sightings_24h}x today
                        </>
                      )}
                    </>
                  ) : (
                    "no recent sightings"
                  )}
                </div>
                <p className="mt-1 text-[11px] leading-snug text-foreground/80 line-clamp-2">
                  {it.status}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
