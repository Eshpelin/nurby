"use client";

/**
 * Everything one person (or one unnamed cluster) has been seen doing,
 * opened from a face on the dashboard.
 */

import { useState, useEffect } from "react";
import { useAuth } from "@/lib/auth";
import { formatWith } from "@/lib/time";
  process.env.NEXT_PUBLIC_WEBRTC_URL || "http://localhost:8889";
import type { Camera, PersonActivityItem } from "@/app/dashboard-types";
import { formatTime } from "@/app/dashboard-helpers";

export function PersonActivityModal({ personId, personName, onClose, mode = "person" }: { personId: string; personName: string; onClose: () => void; mode?: "person" | "cluster" }) {
  const { authFetch, token } = useAuth();
  const [items, setItems] = useState<PersonActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [cameraMap, setCameraMap] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const activityUrl = mode === "cluster"
          ? `/api/persons/clusters/activity/${personId}?limit=200`
          : `/api/persons/activity/${personId}?limit=200`;
        const [actRes, camRes] = await Promise.all([
          authFetch(activityUrl),
          authFetch(`/api/cameras`),
        ]);
        if (cancelled) return;
        if (actRes.ok) {
          const all: PersonActivityItem[] = await actRes.json();
          // Filter to last 24h
          const cutoff = Date.now() - 24 * 3600 * 1000;
          setItems(all.filter((i) => i.started_at && new Date(i.started_at).getTime() >= cutoff));
        }
        if (camRes.ok) {
          const cams: Camera[] = await camRes.json();
          setCameraMap(Object.fromEntries(cams.map((c) => [c.id, c.name])));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [personId, authFetch, mode]);

  // Build per-visit sessions (gap > 10 min = new visit)
  const sessions: { start: string; end: string; cameras: Set<string>; items: PersonActivityItem[] }[] = [];
  const sortedAsc = [...items].sort((a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime());
  const SESSION_GAP_MS = 10 * 60 * 1000;
  for (const item of sortedAsc) {
    const t = new Date(item.started_at).getTime();
    const last = sessions[sessions.length - 1];
    if (!last || t - new Date(last.end).getTime() > SESSION_GAP_MS) {
      sessions.push({ start: item.started_at, end: item.ended_at || item.started_at, cameras: new Set([item.camera_id]), items: [item] });
    } else {
      last.end = item.ended_at || item.started_at;
      last.cameras.add(item.camera_id);
      last.items.push(item);
    }
  }
  sessions.reverse(); // show most recent first

  const totalEvents = items.length;
  const totalCams = new Set(items.map((i) => i.camera_id)).size;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-2xl mx-4 rounded-xl border border-border bg-card-elevated shadow-2xl max-h-[85vh] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-full overflow-hidden border border-border bg-muted flex-shrink-0">
              <img src={`/api/persons/${personId}/photo${token ? `?token=${token}` : ""}`} alt={personName} className="w-full h-full object-cover"
                onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
            </div>
            <div className="min-w-0">
              <h2 className="text-base font-semibold truncate">{personName}</h2>
              <div className="text-[11px] text-muted-foreground">Activity in the last 24 hours</div>
            </div>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-xl leading-none">&times;</button>
        </div>

        {loading ? (
          <div className="p-8 text-center text-sm text-muted-foreground">Loading activity.</div>
        ) : sessions.length === 0 ? (
          <div className="p-8 text-center">
            <p className="text-sm text-muted-foreground">No sightings of {personName} in the last 24 hours.</p>
          </div>
        ) : (
          <div className="overflow-y-auto scrollbar-thin">
            {/* Stats strip */}
            <div className="grid grid-cols-3 gap-2 px-5 py-3 border-b border-border bg-card/30">
              <div>
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider">Visits</div>
                <div className="text-sm font-semibold">{sessions.length}</div>
              </div>
              <div>
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider">Events</div>
                <div className="text-sm font-semibold">{totalEvents}</div>
              </div>
              <div>
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider">Cameras</div>
                <div className="text-sm font-semibold">{totalCams}</div>
              </div>
            </div>

            {/* Visits / sessions */}
            <div className="p-5 space-y-4">
              {sessions.map((s, i) => {
                const start = new Date(s.start);
                const end = new Date(s.end);
                const durMin = Math.max(1, Math.round((end.getTime() - start.getTime()) / 60000));
                const camNames = Array.from(s.cameras).map((id) => cameraMap[id] || "Unknown");
                return (
                  <div key={i} className="rounded-lg border border-border bg-card/50 overflow-hidden">
                    <div className="px-3 py-2 border-b border-border/50 flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="text-xs font-semibold">
                          {formatWith(start, { weekday: "short", hour: "numeric", minute: "2-digit" })}
                          {" \u2192 "}
                          {formatWith(end, { hour: "numeric", minute: "2-digit" })}
                        </div>
                        <div className="text-[11px] text-muted-foreground">
                          {durMin} min \u00b7 {camNames.join(", ")}
                        </div>
                      </div>
                      <span className="text-[10px] text-muted-foreground">{s.items.length} event{s.items.length > 1 ? "s" : ""}</span>
                    </div>
                    <div className="divide-y divide-border/50">
                      {s.items.slice().reverse().map((it) => (
                        <div key={it.observation_id} className="flex gap-3 p-2.5">
                          {it.thumbnail_path ? (
                            <img src={`/api/observations/${it.observation_id}/thumbnail${token ? `?token=${token}` : ""}`} alt=""
                              className="w-20 h-14 flex-shrink-0 rounded object-cover bg-black" />
                          ) : (
                            <div className="w-20 h-14 flex-shrink-0 rounded bg-muted" />
                          )}
                          <div className="flex-1 min-w-0">
                            <div className="flex items-start justify-between gap-2">
                              <p className="text-xs leading-snug line-clamp-2">
                                {it.vlm_description || "Motion detected"}
                              </p>
                              <span className="text-[10px] text-muted-foreground font-mono flex-shrink-0">
                                {formatTime(it.started_at)}
                              </span>
                            </div>
                            <div className="flex flex-wrap gap-1 mt-1">
                              <span className="px-1 py-0.5 text-[9px] rounded bg-muted/50 text-muted-foreground">{it.camera_name || cameraMap[it.camera_id] || "Unknown"}</span>
                              {(it.object_detections?.objects || []).slice(0, 3).map((d, di) => (
                                <span key={di} className="px-1 py-0.5 text-[9px] rounded bg-blue-900/30 text-blue-300 border border-blue-800/40">{d.label}</span>
                              ))}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}


